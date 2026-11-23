"""Create a manifest-backed image of an existing Stratis XFS filesystem.

Only filesystem data is captured. Pool metadata and backing devices are not
part of this image; restore must target a separately provisioned Stratis FS.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from typing import Any, Callable, Mapping

from .capture import CaptureCancelled, CaptureError, capture_partition
from .image_manifest import ImageManifest, ManifestValidationError
from .image_publication import ImagePublicationError, publish_image_set
from .image_security import ImageSecurityError, encrypt_artifact, preflight_image_security


class StratisFilesystemCaptureError(RuntimeError):
    """A Stratis filesystem image could not be safely captured."""


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _walk_devices(items):
    for item in items:
        if not isinstance(item, Mapping):
            continue
        yield item
        yield from _walk_devices(item.get("children") or [])


def _stratis_source(inventory: Mapping[str, Any], source_path: str):
    topology = inventory.get("stratis_topology")
    if not isinstance(topology, Mapping) or topology.get("status") != "available":
        raise StratisFilesystemCaptureError(
            "Stratis metadata is unavailable or incomplete; refusing filesystem capture"
        )
    matches = []
    for pool in topology.get("pools") or []:
        if not isinstance(pool, Mapping):
            continue
        for filesystem in pool.get("filesystems") or []:
            if isinstance(filesystem, Mapping) and source_path in {
                filesystem.get("device"), filesystem.get("mapper_device")
            }:
                matches.append((pool, filesystem))
    if len(matches) != 1:
        raise StratisFilesystemCaptureError(
            "source must identify exactly one active Stratis filesystem"
        )
    pool, filesystem = matches[0]
    if pool.get("alerts_reported") is not False:
        raise StratisFilesystemCaptureError("Stratis pool reports alerts or alert status is unavailable")
    for label, value in (("pool UUID", pool.get("uuid")), ("filesystem UUID", filesystem.get("uuid"))):
        if not isinstance(value, str) or not _UUID.fullmatch(value):
            raise StratisFilesystemCaptureError(f"Stratis {label} is missing or invalid")
    if not isinstance(pool.get("name"), str) or not pool["name"]:
        raise StratisFilesystemCaptureError("Stratis pool name is unavailable")
    if not isinstance(filesystem.get("name"), str) or not filesystem["name"]:
        raise StratisFilesystemCaptureError("Stratis filesystem name is unavailable")
    if filesystem.get("logical_size_bytes") is None:
        raise StratisFilesystemCaptureError("Stratis filesystem logical capacity is unknown")
    return pool, filesystem


def capture_stratis_filesystem_image(
    source_path: str,
    image_id: str,
    repository: str | os.PathLike[str],
    inventory: Mapping[str, Any],
    *,
    compression: str = "none",
    compression_level: int | None = None,
    executables: Mapping[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
    age_recipients_file: str | os.PathLike[str] | None = None,
) -> ImageManifest:
    """Capture one active Stratis XFS filesystem and publish its manifest set."""
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
        raise StratisFilesystemCaptureError("image_id must be a safe filename-compatible identifier")
    if not isinstance(source_path, str) or not source_path.startswith("/dev/") or "\x00" in source_path:
        raise StratisFilesystemCaptureError("source_path must be an absolute /dev path")
    if not isinstance(inventory, Mapping):
        raise StratisFilesystemCaptureError("Stratis filesystem capture requires a current inventory")
    repo = os.path.abspath(os.fspath(repository))
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode):
            raise StratisFilesystemCaptureError("repository must be a real directory")
    except OSError as exc:
        raise StratisFilesystemCaptureError("repository directory is unavailable") from exc
    available = executables or {}
    try:
        preflight_image_security(age_recipients_file=age_recipients_file, age_executable=available.get("age"))
        pool, filesystem_info = _stratis_source(inventory, source_path)
    except (ImageSecurityError, StratisFilesystemCaptureError) as exc:
        raise StratisFilesystemCaptureError(f"Stratis capture preflight failed: {exc}") from exc

    devices = [item for item in _walk_devices(inventory.get("devices") or [])
               if item.get("path") == source_path]
    if len(devices) != 1:
        raise StratisFilesystemCaptureError("Stratis block device must exist exactly once in block inventory")
    device = devices[0]
    if device.get("type") != "dm":
        raise StratisFilesystemCaptureError("Stratis filesystem must resolve to its active device-mapper block device")
    if str(device.get("filesystem") or "").lower() != "xfs":
        raise StratisFilesystemCaptureError("only XFS-backed Stratis filesystems are supported")
    size = device.get("size_bytes")
    logical_size = filesystem_info.get("logical_size_bytes")
    sector = device.get("logical_sector_size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise StratisFilesystemCaptureError("Stratis block-device size is unknown")
    if isinstance(logical_size, bool) or not isinstance(logical_size, int) or logical_size <= 0:
        raise StratisFilesystemCaptureError("Stratis filesystem logical size is invalid")
    if size != logical_size:
        raise StratisFilesystemCaptureError("Stratis CLI logical size and active block-device size disagree")
    if isinstance(sector, bool) or sector not in {512, 4096}:
        raise StratisFilesystemCaptureError("Stratis logical sector size is unknown or unsupported")
    if device.get("mountpoints"):
        raise StratisFilesystemCaptureError("Stratis filesystem is mounted; consistent capture is not established")
    if filesystem_info.get("used_bytes") is None:
        raise StratisFilesystemCaptureError("Stratis filesystem used-byte accounting is unavailable")

    suffix = {"none": "", "gzip": ".gz", "xz": ".xz", "zstd": ".zst", "lz4": ".lz4"}.get(compression)
    if suffix is None:
        raise StratisFilesystemCaptureError("compression must be none, gzip, xz, zstd or lz4")
    partclone_xfs = available.get("partclone.xfs") or shutil.which("partclone.xfs")
    if not partclone_xfs:
        raise StratisFilesystemCaptureError(
            "partclone.xfs is required for Stratis capture; raw imaging fallback is disabled"
        )
    capture_executables = dict(available)
    capture_executables["partclone.xfs"] = partclone_xfs
    artifact_name = f"{image_id}.img{suffix}"
    manifest_name = f"{image_id}.manifest.json"
    storage = {
        "schema_version": 1,
        "capture_scope": "stratis_filesystem_bytes",
        "source_layer": "stratis_filesystem",
        "stratis_pool_name": pool["name"],
        "stratis_pool_uuid": pool["uuid"],
        "stratis_filesystem_name": filesystem_info["name"],
        "stratis_filesystem_uuid": filesystem_info["uuid"],
        "dependencies": [{
            "kind": "stratis_pool", "identity": pool["uuid"],
            "included_in_source_bytes": False,
        }],
    }
    stage = tempfile.mkdtemp(prefix=".feclora-stratis-filesystem-set-", dir=repo)
    try:
        artifact = capture_partition(
            source_path, "xfs", stage, artifact_name, None, capture_executables,
            compression=compression, compression_level=compression_level,
            device_validator=device_validator, popen_factory=popen_factory,
            source_safety_check=source_safety_check, expected_size_bytes=size,
            effective_uid=effective_uid, progress_callback=progress_callback,
            artifact_role="stratis-filesystem-image",
        )
        if age_recipients_file is not None:
            artifact = encrypt_artifact(
                os.path.join(stage, artifact_name), artifact, age_recipients_file,
                age_executable=available.get("age"),
            )
            artifact_name = artifact.filename
        manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": image_id,
            "image_type": "stratis_filesystem", "source_size_bytes": size,
            "logical_sector_size": sector, "partition_table": "none",
            "artifacts": [artifact.to_dict()], "storage": storage,
        })
        fd = os.open(os.path.join(stage, manifest_name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(manifest.to_json())
            output.flush()
            os.fsync(output.fileno())
        try:
            publish_image_set(repo, stage, [artifact_name, manifest_name])
        except FileExistsError as exc:
            raise StratisFilesystemCaptureError("image artifact already exists") from exc
        except ImagePublicationError as exc:
            raise StratisFilesystemCaptureError(str(exc)) from exc
        return manifest
    except CaptureCancelled:
        raise
    except (CaptureError, ImageSecurityError, ManifestValidationError, OSError) as exc:
        raise StratisFilesystemCaptureError(f"Stratis filesystem image capture failed: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
