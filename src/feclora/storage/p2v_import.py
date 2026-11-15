"""Import a verified P2V QCOW2 into Feclora's native whole-disk image format."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from feclora.storage.image_manifest import ImageArtifact, ImageManifest
from feclora.storage.image_publication import publish_image_set


class P2VImportError(RuntimeError):
    """A P2V QCOW2 could not be safely imported as a Feclora image."""


def _run(argv: list[str], runner: Callable[..., Any]) -> Any:
    try:
        result = runner(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=24 * 60 * 60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise P2VImportError(f"could not execute {Path(argv[0]).name}: {exc}") from exc
    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise P2VImportError(f"{Path(argv[0]).name} failed" + (f": {detail[:512]}" if detail else ""))
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_sidecar(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
            raise P2VImportError("P2V metadata must be a regular file no larger than 64 KiB")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    except P2VImportError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise P2VImportError("cannot safely read P2V metadata") from exc
    finally:
        if "fd" in locals() and fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise P2VImportError("P2V metadata must be a JSON object")
    return value


def _copy_verified_source(source: Path, destination: Path, expected_size: int, expected_digest: str) -> None:
    source_fd = None
    destination_fd = None
    digest = hashlib.sha256()
    size = 0
    try:
        source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_size != expected_size:
            raise P2VImportError("P2V source changed or is not a regular file")
        destination_fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        with os.fdopen(source_fd, "rb") as incoming, os.fdopen(destination_fd, "wb") as outgoing:
            source_fd = destination_fd = None
            while True:
                chunk = incoming.read(1024 * 1024)
                if not chunk:
                    break
                outgoing.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except P2VImportError:
        raise
    except OSError as exc:
        raise P2VImportError(f"cannot stage P2V source safely: {exc}") from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if destination_fd is not None:
            os.close(destination_fd)
    if size != expected_size or digest.hexdigest() != expected_digest:
        raise P2VImportError("P2V source changed or failed SHA-256 verification while staging")


def import_p2v_qcow2(
    repository: str | os.PathLike[str],
    source_image_id: str,
    image_id: str,
    *,
    qemu_img: str | None = None,
    losetup: str | None = None,
    sfdisk: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> ImageManifest:
    """Convert a committed P2V QCOW2 into a manifest-backed raw disk image.

    The source QCOW2 and its sidecar remain unchanged. The imported image is a
    new native Feclora image set, published manifest-last without replacement.
    Partition-table metadata is marked unknown: this import preserves sectors
    but does not claim to have repaired guest boot drivers or firmware settings.
    """
    for value, label in ((source_image_id, "source_image_id"), (image_id, "image_id")):
        if (not isinstance(value, str) or not value
                or len(value) > 128 or not value[0].isalnum()
                or any(not (ch.isalnum() or ch in "_.-") for ch in value)):
            raise P2VImportError(f"{label} is invalid")
    if source_image_id == image_id:
        raise P2VImportError("imported image_id must differ from the source P2V image_id")
    repo = Path(repository)
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise P2VImportError("image repository is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode) or stat.S_ISLNK(repo_info.st_mode):
        raise P2VImportError("image repository must be a real directory")
    source = repo / f"{source_image_id}.qcow2"
    sidecar = repo / f"{source_image_id}.p2v.json"
    try:
        metadata = _read_sidecar(sidecar)
    except P2VImportError:
        raise
    required_metadata = {
        "schema_version", "image_id", "format", "source_device", "virtual_size_bytes",
        "logical_sector_size", "file_size_bytes", "qcow2_sha256", "verified", "bootability_note",
    }
    if (not isinstance(metadata, dict) or set(metadata) != required_metadata
            or isinstance(metadata.get("schema_version"), bool) or metadata.get("schema_version") != 1
            or metadata.get("image_id") != source_image_id or metadata.get("format") != "qcow2"
            or metadata.get("verified") is not True
            or not isinstance(metadata.get("source_device"), str)
            or not metadata["source_device"].startswith("/dev/")
            or not isinstance(metadata.get("bootability_note"), str)
            or isinstance(metadata.get("file_size_bytes"), bool)
            or not isinstance(metadata.get("file_size_bytes"), int) or metadata.get("file_size_bytes") <= 0
            or not isinstance(metadata.get("qcow2_sha256"), str)
            or len(metadata.get("qcow2_sha256")) != 64):
        raise P2VImportError("P2V sidecar does not match the QCOW2 source")
    virtual_size = metadata.get("virtual_size_bytes")
    if isinstance(virtual_size, bool) or not isinstance(virtual_size, int) or virtual_size <= 0:
        raise P2VImportError("P2V sidecar has an invalid virtual disk size")
    logical_sector_size = metadata.get("logical_sector_size")
    if isinstance(logical_sector_size, bool) or logical_sector_size not in {512, 4096}:
        raise P2VImportError("P2V sidecar has an invalid or missing logical sector size")
    names = [f"{image_id}.disk.raw", f"{image_id}.sfdisk", f"{image_id}.manifest.json"]
    if any(os.path.lexists(repo / name) for name in names):
        raise P2VImportError("imported Feclora image identifier already exists")
    qemu_img = qemu_img or shutil.which("qemu-img")
    losetup = losetup or shutil.which("losetup")
    sfdisk = sfdisk or shutil.which("sfdisk")
    if not qemu_img or not losetup or not sfdisk:
        raise P2VImportError("qemu-img, losetup and sfdisk are required for P2V import")
    try:
        available_bytes = shutil.disk_usage(repo).free
    except OSError as exc:
        raise P2VImportError(f"cannot check P2V import repository capacity: {exc}") from exc
    required_bytes = metadata["file_size_bytes"] + virtual_size + 64 * 1024 * 1024
    if available_bytes < required_bytes:
        raise P2VImportError(f"insufficient repository capacity: need {required_bytes} bytes, have {available_bytes}")
    stage = Path(tempfile.mkdtemp(prefix=".feclora-p2v-import-", dir=repo))
    os.chmod(stage, 0o700)
    try:
        staged_source = stage / "source.qcow2"
        _copy_verified_source(source, staged_source, metadata["file_size_bytes"], metadata["qcow2_sha256"])
        _run([qemu_img, "check", "-f", "qcow2", str(staged_source)], runner)
        info_result = _run([qemu_img, "info", "--output=json", str(staged_source)], runner)
        try:
            info = json.loads(info_result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise P2VImportError("qemu-img returned invalid source metadata") from exc
        format_specific = info.get("format-specific") if isinstance(info, dict) else None
        format_data = format_specific.get("data", {}) if isinstance(format_specific, dict) else {}
        external_data_file = info.get("data-file") if isinstance(info, dict) else None
        if isinstance(format_data, dict):
            external_data_file = external_data_file or format_data.get("data-file")
        if (not isinstance(info, dict) or info.get("format") != "qcow2"
                or info.get("virtual-size") != virtual_size
                or info.get("backing-filename") or info.get("full-backing-filename")
                or external_data_file or info.get("encrypted") is True
                or (isinstance(format_data, dict) and format_data.get("encrypted") is True)):
            raise P2VImportError("QCOW2 format, dependencies or virtual capacity disagree with its sidecar")
        raw_path = stage / names[0]
        _run([qemu_img, "convert", "-p", "-f", "qcow2", "-O", "raw", str(staged_source), str(raw_path)], runner)
        raw_info = os.lstat(raw_path)
        if not stat.S_ISREG(raw_info.st_mode) or stat.S_ISLNK(raw_info.st_mode) or raw_info.st_size != virtual_size:
            raise P2VImportError("raw conversion did not preserve the declared virtual disk capacity")
        os.chmod(raw_path, 0o600)
        with raw_path.open("rb+") as stream:
            os.fsync(stream.fileno())
        disk_artifact = ImageArtifact(
            filename=names[0], role="disk-image", format="raw", compression="none",
            size_bytes=raw_info.st_size, sha256=_sha256(raw_path),
        )
        loop_device = None
        try:
            attached = _run(
                [losetup, "--find", "--show", "--partscan", "--read-only", "--sector-size", str(logical_sector_size), str(raw_path)], runner,
            )
            loop_device = (getattr(attached, "stdout", "") or "").strip()
            import re
            if not re.fullmatch(r"/dev/loop[0-9]+", loop_device):
                raise P2VImportError("losetup did not return a valid loop-device path")
            dump_result = _run([sfdisk, "--dump", loop_device], runner)
            table_text = (getattr(dump_result, "stdout", "") or "").strip() + "\n"
            label_match = re.search(r"^label:\s*(gpt|dos)\s*$", table_text, re.MULTILINE | re.IGNORECASE)
            if not label_match:
                raise P2VImportError("P2V disk must contain an inspectable GPT or MBR partition table")
            partition_table = "gpt" if label_match.group(1).lower() == "gpt" else "mbr"
            sector_match = re.search(r"^sector-size:\s*(\d+)\s*$", table_text, re.MULTILINE)
            if sector_match and int(sector_match.group(1)) != logical_sector_size:
                raise P2VImportError("partition-table sector size disagrees with P2V source geometry")
            from feclora.storage.partition_range import parse_sfdisk_dump, PartitionRangeError
            try:
                parse_sfdisk_dump(
                    table_text, image_size_bytes=virtual_size,
                    default_sector_size=logical_sector_size,
                )
            except PartitionRangeError as exc:
                raise P2VImportError(f"P2V partition table is invalid: {exc}") from exc
        finally:
            if loop_device:
                _run([losetup, "--detach", loop_device], runner)
        import io
        from feclora.storage.artifact_writer import write_artifact
        table_artifact = write_artifact(
            stage, names[1], io.BytesIO(table_text.encode("utf-8")),
            role="partition-table", image_format="raw",
        )
        manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": image_id, "image_type": "disk",
            "source_size_bytes": virtual_size, "logical_sector_size": logical_sector_size,
            "partition_table": partition_table,
            "artifacts": [disk_artifact.to_dict(), table_artifact.to_dict()],
        })
        manifest_path = stage / names[2]
        fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(manifest.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        publish_image_set(repo, stage, names)
        return manifest
    except Exception:
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
