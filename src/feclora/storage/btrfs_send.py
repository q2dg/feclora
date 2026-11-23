"""Btrfs send/receive subvolume replication engine.

Streams are separate from block-image manifests. Restore receives into a hidden
directory on the destination Btrfs filesystem and exposes the result only after
received-UUID verification.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from typing import Callable, Mapping

from .btrfs_send_manifest import BtrfsSendManifest, BtrfsSendManifestError
from .image_publication import ImagePublicationError, publish_image_set


class BtrfsSendError(RuntimeError):
    """Btrfs subvolume replication was rejected or failed."""


_UUID_LINE = re.compile(r"^UUID:\s*([0-9a-fA-F-]{36})\s*$", re.MULTILINE)
_FS_UUID = re.compile(r"\buuid:\s*([0-9a-fA-F-]{36})", re.IGNORECASE)
_PARENT_UUID_LINE = re.compile(r"^Parent UUID:\s*(.*?)\s*$", re.MULTILINE)
_RECEIVED_UUID_LINE = re.compile(r"^Received UUID:\s*(.*?)\s*$", re.MULTILINE)
_SUBVOL_ID_LINE = re.compile(r"^Subvolume ID:\s*(\d+)\s*$", re.MULTILINE)
_NAME_LINE = re.compile(r"^Name:\s*(.*?)\s*$", re.MULTILINE)
_DEVICES_LINE = re.compile(r"^Total devices (\d+) FS bytes used", re.MULTILINE)


def _run(runner: Callable[..., Any], argv: list[str], *, timeout: int = 120) -> Any:
    try:
        return runner(argv, check=True, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BtrfsSendError(f"command failed ({Path(argv[0]).name}): {exc}") from exc


def _optional_uuid(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    value = match.group(1).strip().lower()
    return value if value and value != "-" else None


def _real_directory(path: str | os.PathLike[str], label: str) -> Path:
    candidate = Path(path)
    try:
        info = os.lstat(candidate)
    except OSError as exc:
        raise BtrfsSendError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise BtrfsSendError(f"{label} must be a real directory, not a symlink")
    return candidate.resolve(strict=True)


def _subvolume_info(path: Path, btrfs: str, runner: Callable[..., Any]) -> dict[str, Any]:
    output = _run(runner, [btrfs, "subvolume", "show", str(path)]).stdout
    uuid_match = _UUID_LINE.search(output)
    id_match = _SUBVOL_ID_LINE.search(output)
    name_match = _NAME_LINE.search(output)
    if not uuid_match or not id_match or not name_match:
        raise BtrfsSendError(f"btrfs subvolume show returned incomplete metadata for {path}")
    readonly = _run(runner, [btrfs, "property", "get", "-t", "subvol", str(path), "ro"]).stdout.strip()
    if readonly not in {"ro=true", "ro=false"}:
        raise BtrfsSendError(f"cannot establish read-only state for subvolume {path}")
    return {
        "uuid": uuid_match.group(1).lower(), "id": int(id_match.group(1)),
        "name": name_match.group(1),
        "parent_uuid": _optional_uuid(_PARENT_UUID_LINE.search(output)),
        "received_uuid": _optional_uuid(_RECEIVED_UUID_LINE.search(output)),
        "readonly": readonly == "ro=true",
    }


def _filesystem_info(path: Path, btrfs: str, runner: Callable[..., Any]) -> tuple[str, int]:
    output = _run(runner, [btrfs, "filesystem", "show", "--raw", str(path)]).stdout
    uuid_match = _FS_UUID.search(output)
    count_match = _DEVICES_LINE.search(output)
    if not uuid_match or not count_match:
        raise BtrfsSendError(f"cannot establish Btrfs filesystem UUID/device count for {path}")
    return uuid_match.group(1).lower(), int(count_match.group(1))


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    if size <= 0:
        raise BtrfsSendError("btrfs send produced an empty stream")
    return size, digest.hexdigest()


def capture_btrfs_subvolume(
    source_path: str | os.PathLike[str], image_id: str,
    repository: str | os.PathLike[str], *,
    parent_path: str | os.PathLike[str] | None = None,
    executables: Mapping[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
) -> BtrfsSendManifest:
    """Create a full or incremental stream from a stable read-only subvolume."""
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
        raise BtrfsSendError("image_id is invalid")
    source = _real_directory(source_path, "source subvolume")
    repo = _real_directory(repository, "image repository")
    available = dict(executables or {})
    btrfs = available.get("btrfs") or shutil.which("btrfs")
    if not btrfs:
        raise BtrfsSendError("btrfs-progs is required")
    run = runner or subprocess.run
    source_info = _subvolume_info(source, btrfs, run)
    if source_info["name"] != source.name:
        raise BtrfsSendError("source path basename does not match the Btrfs subvolume name")
    filesystem_uuid, device_count = _filesystem_info(source, btrfs, run)
    nested = _run(run, [btrfs, "subvolume", "list", "-o", str(source)]).stdout.strip()
    if nested:
        raise BtrfsSendError("source contains nested Btrfs subvolumes; btrfs send would omit their contents")
    parent = None
    parent_info = None
    if parent_path is not None:
        parent = _real_directory(parent_path, "incremental parent")
        parent_info = _subvolume_info(parent, btrfs, run)
        parent_fs_uuid, _ = _filesystem_info(parent, btrfs, run)
        if parent_fs_uuid != filesystem_uuid or not parent_info["readonly"]:
            raise BtrfsSendError("incremental parent must be read-only and on the source Btrfs filesystem")
    snapshot_container = None
    snapshot = None
    stage = Path(tempfile.mkdtemp(prefix=".feclora-btrfs-send-", dir=repo))
    stream_name = f"{image_id}.btrfs"
    manifest_name = f"{image_id}.manifest.json"
    try:
        if not source_info["readonly"]:
            snapshot_parent = source.parent
            if os.stat(snapshot_parent).st_dev != os.stat(source).st_dev:
                snapshot_parent = source
            snapshot_container = snapshot_parent / f".feclora-send-{uuid.uuid4().hex}"
            snapshot_container.mkdir(mode=0o700)
            snapshot = snapshot_container / source.name
            _run(run, [btrfs, "subvolume", "snapshot", "-r", str(source), str(snapshot)])
        send_source = snapshot if snapshot is not None else source
        send_info = _subvolume_info(send_source, btrfs, run)
        argv = [btrfs, "send"]
        if parent is not None:
            argv.extend(["-p", str(parent)])
        argv.append(str(send_source))
        partial = stage / (stream_name + ".partial")
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                try:
                    run(argv, check=True, stdout=output, stderr=subprocess.PIPE, timeout=24 * 60 * 60)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise BtrfsSendError(f"btrfs send failed: {exc}") from exc
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        size, digest = _hash_file(partial)
        os.replace(partial, stage / stream_name)
        manifest = BtrfsSendManifest.from_dict({
            "schema_version": 1, "image_id": image_id,
            "filesystem_uuid": filesystem_uuid, "subvolume_id": send_info["id"],
            "subvolume_uuid": send_info["uuid"], "subvolume_name": source.name,
            "device_count": device_count,
            "send_mode": "incremental" if parent is not None else "full",
            "stream_parent_uuid": parent_info["uuid"] if parent_info is not None else None,
            "stream_filename": stream_name, "stream_size_bytes": size,
            "stream_sha256": digest, "compression": "none",
            "parent_uuid": send_info["parent_uuid"],
            "received_uuid": send_info["received_uuid"],
        })
        manifest_path = stage / manifest_name
        fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(manifest.to_json())
            output.flush()
            os.fsync(output.fileno())
        try:
            publish_image_set(repo, stage, [stream_name, manifest_name])
        except (FileExistsError, ImagePublicationError) as exc:
            raise BtrfsSendError(f"cannot publish Btrfs send image set: {exc}") from exc
        return manifest
    except BtrfsSendManifestError as exc:
        raise BtrfsSendError(f"invalid Btrfs send metadata: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if snapshot is not None:
            try:
                if snapshot.exists():
                    _run(run, [btrfs, "subvolume", "delete", str(snapshot)])
                snapshot_container.rmdir()
            except (BtrfsSendError, OSError):
                pass


def restore_btrfs_subvolume(
    manifest_path: str | os.PathLike[str], repository: str | os.PathLike[str],
    target_directory: str | os.PathLike[str], *,
    parent_path: str | os.PathLike[str] | None = None,
    executables: Mapping[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
) -> Path:
    """Receive to hidden staging and expose the result only after provenance checks."""
    repo = _real_directory(repository, "image repository")
    target = _real_directory(target_directory, "Btrfs destination")
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = repo / manifest_file
    try:
        info = os.lstat(manifest_file)
        if not stat.S_ISREG(info.st_mode):
            raise BtrfsSendError("manifest must be a regular file")
        manifest = BtrfsSendManifest.from_json(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, BtrfsSendManifestError) as exc:
        raise BtrfsSendError(f"cannot load Btrfs send manifest: {exc}") from exc
    if manifest.compression != "none":
        raise BtrfsSendError("this receiver supports uncompressed Btrfs send streams only")
    stream = repo / manifest.stream_filename
    try:
        stream_info = os.lstat(stream)
    except OSError as exc:
        raise BtrfsSendError("Btrfs send stream is unavailable") from exc
    if not stat.S_ISREG(stream_info.st_mode):
        raise BtrfsSendError("Btrfs send stream must be a regular file")
    size, digest = _hash_file(stream)
    if size != manifest.stream_size_bytes or digest != manifest.stream_sha256:
        raise BtrfsSendError("Btrfs send stream size or SHA-256 does not match its manifest")
    available = dict(executables or {})
    btrfs = available.get("btrfs") or shutil.which("btrfs")
    if not btrfs:
        raise BtrfsSendError("btrfs-progs is required")
    run = runner or subprocess.run
    _filesystem_info(target, btrfs, run)
    if manifest.send_mode == "incremental":
        if parent_path is None:
            raise BtrfsSendError("incremental restore requires the received parent subvolume")
        parent = _real_directory(parent_path, "received incremental parent")
        parent_info = _subvolume_info(parent, btrfs, run)
        if not parent_info["readonly"] or parent_info["received_uuid"] != manifest.stream_parent_uuid:
            raise BtrfsSendError("destination does not contain the required read-only received parent")
        if os.path.commonpath((str(target), str(parent))) != str(target):
            raise BtrfsSendError("incremental parent must be inside the selected Btrfs destination")
    destination = target / manifest.subvolume_name
    if os.path.lexists(destination):
        raise BtrfsSendError("destination subvolume path already exists")
    stage = target / f".feclora-receive-{manifest.image_id}-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        try:
            with stream.open("rb") as input_stream:
                run([btrfs, "receive", str(stage)], check=True, stdin=input_stream,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=24 * 60 * 60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BtrfsSendError(f"btrfs receive failed; partial data remains quarantined at {stage}") from exc
        entries = list(stage.iterdir())
        if len(entries) != 1 or not entries[0].is_dir() or entries[0].is_symlink():
            raise BtrfsSendError(f"btrfs receive produced an unexpected staging layout at {stage}")
        received = entries[0]
        received_info = _subvolume_info(received, btrfs, run)
        if (received_info["name"] != manifest.subvolume_name
                or received_info["received_uuid"] != manifest.subvolume_uuid):
            raise BtrfsSendError(f"received subvolume provenance mismatch; staging retained at {stage}")
        if os.path.lexists(destination):
            raise BtrfsSendError("destination path appeared during receive; staging retained")
        os.rename(received, destination)
        stage.rmdir()
        directory_fd = os.open(target, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    except BtrfsSendError:
        raise
    except OSError as exc:
        raise BtrfsSendError(f"cannot publish received subvolume; staging retained at {stage}: {exc}") from exc
