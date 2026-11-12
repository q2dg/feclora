"""Create a manifest-backed logical-volume image set.

The operation captures only an already active, inventoried LVM LV. It does
not activate groups, create snapshots, unlock LUKS, or modify storage.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from typing import Any, Callable, Mapping

from .capture import CaptureCancelled, CaptureError, capture_logical_volume
from .capture_plan import CapturePlanError, plan_storage_capture
from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import (
    ImageSecurityError, encrypt_artifact, preflight_image_security,
)


class LogicalVolumeImageCaptureError(RuntimeError):
    """A logical-volume image set could not be safely committed."""


def capture_logical_volume_image(
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
    """Capture one healthy active LV and atomically publish its manifest set."""
    if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
        raise LogicalVolumeImageCaptureError("image_id must be a safe filename-compatible identifier")
    repo = os.path.abspath(os.fspath(repository))
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise LogicalVolumeImageCaptureError("repository directory is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode) or stat.S_ISLNK(repo_info.st_mode):
        raise LogicalVolumeImageCaptureError("repository must be a real directory")
    available = executables or {}
    try:
        preflight_image_security(
            age_recipients_file=age_recipients_file,
            age_executable=available.get("age"),
        )
        plan = plan_storage_capture(dict(inventory), source_path, "logical_volume")
    except (ImageSecurityError, CapturePlanError) as exc:
        raise LogicalVolumeImageCaptureError(f"logical-volume capture preflight failed: {exc}") from exc
    if plan.get("blockers"):
        raise LogicalVolumeImageCaptureError(
            "logical-volume source has unresolved storage dependencies: "
            + "; ".join(plan["blockers"])
        )
    storage_metadata = plan.get("manifest_storage")
    if (not isinstance(storage_metadata, dict)
            or storage_metadata.get("source_layer") != "lvm_logical_volume"
            or not storage_metadata.get("lvm_vg_name")
            or not storage_metadata.get("lvm_lv_name")):
        raise LogicalVolumeImageCaptureError(
            "capture planner could not prove the source is a uniquely identified LVM logical volume"
        )
    source = plan.get("source") or {}
    size = source.get("size_bytes")
    source_devices = [
        device for device in _walk_devices(inventory.get("devices") or [])
        if device.get("path") == source_path
    ]
    if len(source_devices) != 1:
        raise LogicalVolumeImageCaptureError("logical-volume block identity is missing or ambiguous")
    source_device = source_devices[0]
    sector = source_device.get("logical_sector_size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise LogicalVolumeImageCaptureError("logical-volume size is unknown")
    if source_device.get("size_bytes") != size:
        raise LogicalVolumeImageCaptureError("capture plan and block-inventory logical-volume sizes disagree")
    if isinstance(sector, bool) or sector not in {512, 4096}:
        raise LogicalVolumeImageCaptureError("logical-volume logical sector size is unknown or unsupported")
    filesystem = source.get("filesystem")
    suffix = {"none": "", "gzip": ".gz", "xz": ".xz", "zstd": ".zst", "lz4": ".lz4"}.get(compression)
    if suffix is None:
        raise LogicalVolumeImageCaptureError("compression must be none, gzip, xz, zstd or lz4")
    artifact_name = f"{image_id}.img{suffix}"
    manifest_name = f"{image_id}.manifest.json"
    stage = tempfile.mkdtemp(prefix=".feclora-logical-volume-set-", dir=repo)
    try:
        artifact = capture_logical_volume(
            source_path, filesystem, stage, artifact_name, inventory, available,
            compression=compression, compression_level=compression_level,
            device_validator=device_validator, popen_factory=popen_factory,
            source_safety_check=source_safety_check, effective_uid=effective_uid,
            progress_callback=progress_callback,
        )
        if age_recipients_file is not None:
            artifact = encrypt_artifact(
                os.path.join(stage, artifact_name), artifact, age_recipients_file,
                age_executable=available.get("age"),
            )
            artifact_name = artifact.filename
        manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": image_id,
            "image_type": "logical_volume",
            "source_size_bytes": size,
            "logical_sector_size": sector,
            "partition_table": "none",
            "artifacts": [artifact.to_dict()],
            "storage": storage_metadata,
        })
        manifest_stage = os.path.join(stage, manifest_name)
        fd = os.open(manifest_stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(manifest.to_json())
            output.flush()
            os.fsync(output.fileno())
        signature_name = None
        names = [artifact_name]
        if signature_name is not None:
            names.append(signature_name)
        names.append(manifest_name)
        try:
            publish_image_set(repo, stage, names)
        except FileExistsError as exc:
            raise LogicalVolumeImageCaptureError("image artifact already exists") from exc
        except ImagePublicationError as exc:
            raise LogicalVolumeImageCaptureError(str(exc)) from exc
        return manifest
    except CaptureCancelled:
        raise
    except (CaptureError, ImageSecurityError, ManifestValidationError, OSError) as exc:
        raise LogicalVolumeImageCaptureError(f"logical-volume image capture failed: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _walk_devices(items: list[dict[str, Any]]):
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item
        yield from _walk_devices(item.get("children") or [])
