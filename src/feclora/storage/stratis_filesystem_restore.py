"""Restore a Stratis filesystem image into a pre-created Stratis filesystem.

The pool and target filesystem must already exist and be active. This module
writes only XFS filesystem data; it never creates pools or Stratis filesystems.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .image_manifest import ImageManifest, ManifestValidationError
from .partition_restore import (
    PartitionRestoreError,
    _decompress_to_temp,
    _verified_artifact_stream,
    _verify_partclone_target,
)
from .privilege import PrivilegeError, privileged_argv
from .source_safety import SourceSafetyError, check_capture_source_safe
from .process_control import stop_process


class StratisFilesystemRestoreError(RuntimeError):
    """A Stratis filesystem restore was rejected or failed."""


def _walk_devices(items):
    for item in items:
        if not isinstance(item, Mapping):
            continue
        yield item
        yield from _walk_devices(item.get("children") or [])


def _target_record(inventory: Mapping[str, Any], target_path: str, source_uuid: str):
    topology = inventory.get("stratis_topology")
    if not isinstance(topology, Mapping) or topology.get("status") != "available":
        raise StratisFilesystemRestoreError(
            "Stratis metadata is unavailable or incomplete; refusing restore"
        )
    matches = []
    for pool in topology.get("pools") or []:
        if not isinstance(pool, Mapping):
            continue
        for filesystem in pool.get("filesystems") or []:
            if isinstance(filesystem, Mapping) and target_path in {
                filesystem.get("device"), filesystem.get("mapper_device")
            }:
                matches.append((pool, filesystem))
    if len(matches) != 1:
        raise StratisFilesystemRestoreError(
            "restore target must identify exactly one active Stratis filesystem"
        )
    pool, filesystem = matches[0]
    pool_uuid = pool.get("uuid")
    filesystem_uuid = filesystem.get("uuid")
    if not isinstance(pool_uuid, str) or not pool_uuid:
        raise StratisFilesystemRestoreError("target Stratis pool UUID is unavailable")
    if not isinstance(filesystem_uuid, str) or not filesystem_uuid:
        raise StratisFilesystemRestoreError("target Stratis filesystem UUID is unavailable")
    if filesystem_uuid.lower() == source_uuid.lower():
        raise StratisFilesystemRestoreError("restore target is the source Stratis filesystem")
    logical_size = filesystem.get("logical_size_bytes")
    if isinstance(logical_size, bool) or not isinstance(logical_size, int) or logical_size <= 0:
        raise StratisFilesystemRestoreError("target Stratis logical capacity is unknown")
    devices = [item for item in _walk_devices(inventory.get("devices") or [])
               if item.get("path") == target_path]
    if len(devices) != 1:
        raise StratisFilesystemRestoreError("target block device must exist exactly once in inventory")
    device = devices[0]
    if device.get("type") != "dm" or str(device.get("filesystem") or "").lower() != "xfs":
        raise StratisFilesystemRestoreError("target must be an active XFS-backed Stratis device-mapper filesystem")
    size = device.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size != logical_size:
        raise StratisFilesystemRestoreError("target Stratis logical capacity and block-device size disagree")
    if device.get("mountpoints"):
        raise StratisFilesystemRestoreError("target Stratis filesystem is mounted; refusing destructive restore")
    major_minor = device.get("major_minor")
    if not isinstance(major_minor, str) or not major_minor:
        raise StratisFilesystemRestoreError("target block-device kernel identity is unavailable")
    return (pool_uuid, filesystem_uuid, major_minor, logical_size)


def _target_geometry(target: str, lsblk: str, runner: Callable[..., Any]):
    try:
        result = runner(
            [lsblk, "--bytes", "--noheadings", "--nodeps",
             "--output", "SIZE,TYPE,LOG-SEC,RO", target],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StratisFilesystemRestoreError(f"cannot inspect Stratis restore target: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) != 4 or fields[1] != "dm":
        raise StratisFilesystemRestoreError("restore target must be exactly one device-mapper block device")
    try:
        size, sector = int(fields[0]), int(fields[2])
    except ValueError as exc:
        raise StratisFilesystemRestoreError("lsblk returned invalid Stratis target geometry") from exc
    if size <= 0 or sector not in {512, 4096} or fields[3] == "1":
        raise StratisFilesystemRestoreError("Stratis target geometry is invalid or read-only")
    return size, sector


def _load_manifest(path: Path) -> ImageManifest:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            raise StratisFilesystemRestoreError("manifest must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            return ImageManifest.from_json(stream.read())
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise StratisFilesystemRestoreError(f"cannot load valid Stratis filesystem manifest: {exc}") from exc


def restore_stratis_filesystem_image(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    target_path: str,
    *,
    confirmation: str,
    inventory: Mapping[str, Any] | None = None,
    inventory_provider: Callable[[], Mapping[str, Any]] | None = None,
    executables: Mapping[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    target_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
) -> ImageManifest:
    """Restore XFS data to a distinct, pre-created and unmounted Stratis filesystem."""
    if not isinstance(target_path, str) or not target_path.startswith("/dev/") or "\x00" in target_path:
        raise StratisFilesystemRestoreError("target must be an absolute /dev/ path")
    if confirmation != f"ERASE {target_path}":
        raise StratisFilesystemRestoreError(f"explicit confirmation required: ERASE {target_path}")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(target_path):
            raise StratisFilesystemRestoreError("target is not an accessible block device")
        initial_device_number = os.stat(target_path).st_rdev if device_validator is None else None
    except OSError as exc:
        raise StratisFilesystemRestoreError(f"cannot inspect target block device: {exc}") from exc

    repo = os.path.abspath(os.fspath(repository))
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode):
            raise StratisFilesystemRestoreError("image repository must be a real directory")
    except OSError as exc:
        raise StratisFilesystemRestoreError("image repository is unavailable") from exc
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = Path(repo) / manifest_file
    manifest = _load_manifest(manifest_file)
    if manifest.image_type != "stratis_filesystem":
        raise StratisFilesystemRestoreError("Stratis restore requires a stratis_filesystem image manifest")
    storage = manifest.storage or {}
    source_uuid = storage.get("stratis_filesystem_uuid")
    if not isinstance(source_uuid, str) or not source_uuid:
        raise StratisFilesystemRestoreError("manifest has no source Stratis filesystem UUID")
    artifacts = [item for item in manifest.artifacts if item.role == "stratis-filesystem-image"]
    if len(artifacts) != 1:
        raise StratisFilesystemRestoreError("manifest must contain exactly one Stratis filesystem data artifact")
    artifact = artifacts[0]
    if artifact.format != "partclone" or artifact.filesystem != "xfs":
        raise StratisFilesystemRestoreError("Stratis restore accepts Partclone XFS artifacts only")

    available = dict(executables or {})
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    partclone = available.get("partclone.xfs") or shutil.which("partclone.xfs")
    xfs_repair = available.get("xfs_repair") or shutil.which("xfs_repair")
    if not lsblk or not partclone or not xfs_repair:
        raise StratisFilesystemRestoreError("lsblk, partclone.xfs and xfs_repair are required")
    available["xfs_repair"] = xfs_repair
    run = runner or subprocess.run
    if inventory_provider is not None:
        current_inventory = inventory_provider()
    elif inventory is not None:
        current_inventory = inventory
    else:
        from .inventory import collect_inventory
        current_inventory = collect_inventory()
    identity = _target_record(current_inventory, target_path, source_uuid)
    target_size, target_sector = _target_geometry(target_path, lsblk, run)
    if target_size != identity[3] or target_size < manifest.source_size_bytes:
        raise StratisFilesystemRestoreError("target Stratis filesystem is smaller than the image or has inconsistent capacity")
    if target_sector != manifest.logical_sector_size:
        raise StratisFilesystemRestoreError("target logical sector size differs from the image")
    safety = target_safety_check or check_capture_source_safe
    try:
        safety(target_path)
    except SourceSafetyError as exc:
        raise StratisFilesystemRestoreError(f"unsafe Stratis restore target: {exc}") from exc

    staged_path = None
    try:
        with _verified_artifact_stream(repo, artifact, age_identity_file, available.get("age")) as image:
            staged_path, _ = _decompress_to_temp(
                image, artifact.compression, None, tempfile.gettempdir(), available,
            )
        if inventory_provider is not None:
            fresh_inventory = inventory_provider()
        elif inventory is not None:
            fresh_inventory = current_inventory
        else:
            from .inventory import collect_inventory
            fresh_inventory = collect_inventory()
        refreshed_identity = _target_record(fresh_inventory, target_path, source_uuid)
        refreshed_size, refreshed_sector = _target_geometry(target_path, lsblk, run)
        if (refreshed_identity != identity or refreshed_size != target_size
                or refreshed_sector != target_sector
                or refreshed_size < manifest.source_size_bytes):
            raise StratisFilesystemRestoreError("Stratis target identity or geometry changed during preflight")
        if not validator(target_path):
            raise StratisFilesystemRestoreError("Stratis target block-device identity changed")
        if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
            raise StratisFilesystemRestoreError("Stratis target block-device identity changed before restore")
        try:
            safety(target_path)
        except SourceSafetyError as exc:
            raise StratisFilesystemRestoreError(f"Stratis restore target became unsafe: {exc}") from exc

        stderr = tempfile.TemporaryFile(mode="w+b")
        process = None
        factory = popen_factory or subprocess.Popen
        try:
            command = privileged_argv(
                [partclone, "-r", "-F", "-f", "1", "-s", staged_path, "-o", target_path],
                effective_uid=effective_uid,
            )
            process = factory(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=stderr, close_fds=True,
            )
            return_code = process.wait()
            if return_code != 0:
                stderr.seek(0)
                detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
                raise StratisFilesystemRestoreError(
                    f"Partclone XFS restore exited with status {return_code}"
                    + (f": {detail}" if detail else "")
                )
        except (OSError, PrivilegeError) as exc:
            raise StratisFilesystemRestoreError(f"could not execute Stratis filesystem restore: {exc}") from exc
        finally:
            stop_process(process)
            stderr.close()

        if not validator(target_path):
            raise StratisFilesystemRestoreError("Stratis target identity changed before post-restore verification")
        if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
            raise StratisFilesystemRestoreError("Stratis target block-device identity changed before verification")
        try:
            safety(target_path)
            _verify_partclone_target("xfs", target_path, available, run, effective_uid)
        except (SourceSafetyError, PartitionRestoreError) as exc:
            raise StratisFilesystemRestoreError(f"post-restore XFS verification failed: {exc}") from exc
        if inventory_provider is not None:
            verified_inventory = inventory_provider()
            if _target_record(verified_inventory, target_path, source_uuid) != identity:
                raise StratisFilesystemRestoreError("Stratis target identity changed during post-restore verification")
        if progress_callback is not None:
            progress_callback(manifest.source_size_bytes, manifest.source_size_bytes)
    finally:
        if staged_path:
            try:
                os.unlink(staged_path)
            except FileNotFoundError:
                pass
    return manifest
