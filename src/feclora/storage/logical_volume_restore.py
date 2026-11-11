"""Verified restore of a logical-volume image into an existing LVM LV."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import ImageSecurityError, verify_manifest_signature
from .partition_restore import (
    PartitionRestoreError,
    _PARTCLONE,
    _FILESYSTEM_CHECKS,
    _decompress_to_temp,
    _stop_process,
    _verify_partclone_target,
    _verify_raw_readback,
    _verified_artifact_stream,
)
from .privilege import PrivilegeError, privileged_argv
from .profile_executor import RestoreProfileError, preflight_logical_volume_restore
from .source_safety import SourceSafetyError, check_capture_source_safe


class LogicalVolumeRestoreError(RuntimeError):
    """An LVM logical-volume restore was rejected or failed."""


def _load_manifest(path: str | os.PathLike[str]) -> ImageManifest:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise LogicalVolumeRestoreError("manifest must be a regular file")
            raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise LogicalVolumeRestoreError("manifest exceeds the 1 MiB size limit")
            return ImageManifest.from_json(raw)
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise LogicalVolumeRestoreError(f"cannot load valid logical-volume manifest: {exc}") from exc


def _target_geometry(
    target: str, lsblk: str, runner: Callable[..., Any],
) -> tuple[int, int]:
    try:
        result = runner(
            [lsblk, "--bytes", "--noheadings", "--nodeps",
             "--output", "SIZE,TYPE,LOG-SEC,RO", target],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LogicalVolumeRestoreError(f"cannot inspect target logical volume: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) != 4 or fields[1] != "lvm":
        raise LogicalVolumeRestoreError("restore target must be exactly one active LVM logical volume")
    try:
        size, sector_size = int(fields[0]), int(fields[2])
        read_only = fields[3] == "1"
    except ValueError as exc:
        raise LogicalVolumeRestoreError("lsblk returned invalid logical-volume geometry") from exc
    if size <= 0 or sector_size not in {512, 4096} or read_only:
        raise LogicalVolumeRestoreError("target logical-volume geometry is invalid or read-only")
    return size, sector_size


def restore_logical_volume(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    target_path: str,
    *,
    confirmation: str,
    inventory: dict[str, Any] | None = None,
    inventory_provider: Callable[[], dict[str, Any]] | None = None,
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    target_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    minisign_public_key: str | os.PathLike[str] | None = None,
    require_signature: bool = False,
) -> ImageManifest:
    """Restore bytes into an existing LV; no LVM metadata is created or changed."""
    if not isinstance(target_path, str) or not target_path.startswith("/dev/"):
        raise LogicalVolumeRestoreError("target must be an absolute /dev/ path")
    if confirmation != f"ERASE {target_path}":
        raise LogicalVolumeRestoreError(f"explicit confirmation required: ERASE {target_path}")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(target_path):
            raise LogicalVolumeRestoreError("target is not an accessible block device")
        initial_device_number = os.stat(target_path).st_rdev if device_validator is None else None
    except OSError as exc:
        raise LogicalVolumeRestoreError(f"cannot inspect target logical volume: {exc}") from exc

    repo = os.path.abspath(os.fspath(repository))
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode):
            raise LogicalVolumeRestoreError("image repository must be a real directory")
    except OSError as exc:
        raise LogicalVolumeRestoreError("image repository is unavailable") from exc
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = Path(repo) / manifest_file
    manifest = _load_manifest(manifest_file)
    if manifest.image_type != "logical_volume":
        raise LogicalVolumeRestoreError("logical-volume restore requires a logical_volume image manifest")
    artifacts = [item for item in manifest.artifacts if item.role == "logical-volume-image"]
    if len(artifacts) != 1:
        raise LogicalVolumeRestoreError("manifest must contain exactly one logical-volume-image artifact")
    artifact = artifacts[0]

    signature_path = str(manifest_file) + ".minisig"
    signature_present = os.path.lexists(signature_path)
    if require_signature and not signature_present:
        raise LogicalVolumeRestoreError("a minisign signature is required but this image has none")
    if signature_present and minisign_public_key is None:
        raise LogicalVolumeRestoreError("image is signed; a trusted minisign public key is required before restore")
    if minisign_public_key is not None:
        if not signature_present:
            raise LogicalVolumeRestoreError("minisign public key supplied but image signature is missing")
        try:
            verify_manifest_signature(
                str(manifest_file), minisign_public_key, signature_path=signature_path,
                minisign_executable=(executables or {}).get("minisign"),
            )
        except ImageSecurityError as exc:
            raise LogicalVolumeRestoreError(f"manifest signature verification failed: {exc}") from exc

    available = executables or {}
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    dd = available.get("dd") or shutil.which("dd")
    if not lsblk or not dd:
        raise LogicalVolumeRestoreError("lsblk and dd are required for logical-volume restore")
    run = runner or subprocess.run
    current_inventory = inventory if inventory is not None else (
        inventory_provider() if inventory_provider else __import__(
            "feclora.storage.inventory", fromlist=["collect_inventory"]
        ).collect_inventory()
    )
    try:
        preflight = preflight_logical_volume_restore(manifest, current_inventory, target_path)
    except RestoreProfileError as exc:
        raise LogicalVolumeRestoreError(f"logical-volume preflight failed: {exc}") from exc
    target_size, target_sector = _target_geometry(target_path, lsblk, run)
    if target_sector != manifest.logical_sector_size:
        raise LogicalVolumeRestoreError("target logical sector size differs from the image")
    if target_size < manifest.source_size_bytes:
        raise LogicalVolumeRestoreError("target logical volume is smaller than the image")

    if artifact.format == "partclone":
        partclone_name = _PARTCLONE.get(artifact.filesystem or "")
        executable = available.get(partclone_name) if partclone_name else None
        executable = executable or (shutil.which(partclone_name) if partclone_name else None)
        if not executable:
            raise LogicalVolumeRestoreError(
                f"Partclone restore utility is unavailable for filesystem {artifact.filesystem!r}"
            )
        check = _FILESYSTEM_CHECKS.get(artifact.filesystem or "")
        if check is None or not (available.get(check[0]) or shutil.which(check[0])):
            raise LogicalVolumeRestoreError(
                f"a read-only filesystem checker is required for {artifact.filesystem!r}"
            )
    elif artifact.format == "raw":
        executable = dd
    else:
        raise LogicalVolumeRestoreError("unsupported logical-volume image format")

    safety = target_safety_check or check_capture_source_safe
    try:
        safety(target_path)
    except SourceSafetyError as exc:
        raise LogicalVolumeRestoreError(f"unsafe restore target: {exc}") from exc

    staged_path = None
    with _verified_artifact_stream(repo, artifact, age_identity_file, available.get("age")) as image:
        try:
            staged_path, decoded_size = _decompress_to_temp(
                image, artifact.compression,
                manifest.source_size_bytes if artifact.format == "raw" else None,
                tempfile.gettempdir(), available,
            )
            if artifact.format == "raw" and decoded_size != manifest.source_size_bytes:
                raise LogicalVolumeRestoreError("decoded raw image size differs from manifest")
            # Re-inventory immediately before writing: aliases, VG/PV health,
            # target activity, mount state and thin-pool headroom may have changed.
            fresh_inventory = inventory_provider() if inventory_provider else (
                current_inventory if inventory is not None else __import__(
                    "feclora.storage.inventory", fromlist=["collect_inventory"]
                ).collect_inventory()
            )
            try:
                preflight_logical_volume_restore(manifest, fresh_inventory, target_path)
            except RestoreProfileError as exc:
                raise LogicalVolumeRestoreError(f"logical-volume pre-write check failed: {exc}") from exc
            refreshed_size, refreshed_sector = _target_geometry(target_path, lsblk, run)
            if refreshed_size < manifest.source_size_bytes or refreshed_sector != manifest.logical_sector_size:
                raise LogicalVolumeRestoreError("target logical-volume geometry changed during preflight")
            if not validator(target_path):
                raise LogicalVolumeRestoreError("target logical-volume identity changed")
            if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
                raise LogicalVolumeRestoreError("target block-device identity changed before restore")
            try:
                safety(target_path)
            except SourceSafetyError as exc:
                raise LogicalVolumeRestoreError(f"restore target became unsafe: {exc}") from exc

            stderr = tempfile.TemporaryFile(mode="w+b")
            process = None
            factory = popen_factory or subprocess.Popen
            try:
                if artifact.format == "raw":
                    argv = privileged_argv(
                        [dd, f"of={target_path}", "bs=4M", "conv=fsync", "status=none"],
                        effective_uid=effective_uid,
                    )
                    process = factory(
                        argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=stderr, close_fds=True,
                    )
                    if process.stdin is None:
                        raise LogicalVolumeRestoreError("dd did not provide a writable input pipe")
                    written = 0
                    with open(staged_path, "rb") as source:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            view = memoryview(chunk)
                            while view:
                                count = process.stdin.write(view)
                                if count is None or count <= 0:
                                    raise LogicalVolumeRestoreError("dd input pipe stopped accepting data")
                                written += count
                                view = view[count:]
                            if progress_callback:
                                progress_callback(written, manifest.source_size_bytes)
                    process.stdin.close()
                    if written != manifest.source_size_bytes:
                        raise LogicalVolumeRestoreError("written byte count differs from manifest")
                else:
                    argv = privileged_argv(
                        [executable, "-r", "-F", "-f", "1", "-s", staged_path, "-o", target_path],
                        effective_uid=effective_uid,
                    )
                    process = factory(
                        argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=stderr, close_fds=True,
                    )
                return_code = process.wait()
                if return_code != 0:
                    stderr.seek(0)
                    detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
                    raise LogicalVolumeRestoreError(
                        f"restore utility exited with status {return_code}" + (f": {detail}" if detail else "")
                    )
            except (OSError, PrivilegeError) as exc:
                raise LogicalVolumeRestoreError(f"could not execute logical-volume restore: {exc}") from exc
            finally:
                _stop_process(process)
                stderr.close()

            if not validator(target_path):
                raise LogicalVolumeRestoreError("target identity changed before post-restore verification")
            try:
                safety(target_path)
            except SourceSafetyError as exc:
                raise LogicalVolumeRestoreError(f"target became unsafe before verification: {exc}") from exc
            if artifact.format == "raw":
                _verify_raw_readback(
                    dd, target_path, staged_path, manifest.source_size_bytes,
                    popen_factory=factory, effective_uid=effective_uid,
                )
            else:
                try:
                    _verify_partclone_target(
                        artifact.filesystem or "", target_path, available, run, effective_uid,
                    )
                except PartitionRestoreError as exc:
                    raise LogicalVolumeRestoreError(str(exc)) from exc
            if progress_callback:
                progress_callback(manifest.source_size_bytes, manifest.source_size_bytes)
        finally:
            if staged_path:
                try:
                    os.unlink(staged_path)
                except FileNotFoundError:
                    pass
    return manifest
