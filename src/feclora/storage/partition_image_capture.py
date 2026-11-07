"""Create a manifest-backed partition image set from the generic capture engine."""
from __future__ import annotations
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping
from .capture import CaptureCancelled, CaptureError, capture_partition
from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import encrypt_artifact, sign_manifest
from .source_safety import SourceSafetyError, check_capture_source_safe

class PartitionImageCaptureError(RuntimeError):
    """A partition image set could not be safely committed."""

def capture_partition_image(
    source_path: str,
    image_id: str,
    partition_id: str,
    repository: str | os.PathLike[str],
    *,
    compression: str = "none",
    executables: Mapping[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
    age_recipients_file: str | os.PathLike[str] | None = None,
    minisign_secret_key: str | os.PathLike[str] | None = None,
) -> ImageManifest:
    """Capture a partition and publish its data artifact and manifest marker."""
    if not isinstance(image_id, str) or not image_id or len(image_id) > 128:
        raise PartitionImageCaptureError("image_id must be a safe non-empty identifier")
    repo = os.path.abspath(os.fspath(repository))
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode):
            raise PartitionImageCaptureError("repository must be a real directory")
    except OSError as exc:
        raise PartitionImageCaptureError("repository directory is unavailable") from exc
    available = executables or {}
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    if not lsblk:
        raise PartitionImageCaptureError("lsblk is required for partition metadata")
    run = runner or subprocess.run
    try:
        result = run(
            [lsblk, "--bytes", "--noheadings", "--nodeps", "--output",
             "SIZE,LOG-SEC,TYPE,FSTYPE", source_path],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PartitionImageCaptureError(f"cannot inspect source partition: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) < 3 or fields[2] != "part":
        raise PartitionImageCaptureError("source must be exactly one partition")
    try:
        size, sector = int(fields[0]), int(fields[1])
    except ValueError as exc:
        raise PartitionImageCaptureError("lsblk returned invalid partition geometry") from exc
    if size <= 0 or sector not in {512, 4096}:
        raise PartitionImageCaptureError("partition geometry is invalid or unsupported")
    filesystem = fields[3].lower() if len(fields) > 3 else None
    if filesystem in {"", "-"}:
        filesystem = None

    safe_partition_id = partition_id.replace("+", "_")
    stem = f"{image_id}_{safe_partition_id}"
    suffix = {"none": "", "gzip": ".gz", "xz": ".xz"}.get(compression)
    if suffix is None:
        raise PartitionImageCaptureError("compression must be none, gzip or xz")
    artifact_name = f"{stem}.img{suffix}"
    manifest_name = f"{image_id}.manifest.json"
    stage = tempfile.mkdtemp(prefix=".feclora-partition-set-", dir=repo)
    published: list[str] = []
    committed = False
    repository_fd = None
    try:
        artifact = capture_partition(
            source_path, filesystem, stage, artifact_name, partition_id,
            available, compression=compression, device_validator=device_validator,
            popen_factory=popen_factory, source_safety_check=source_safety_check,
            expected_size_bytes=size, effective_uid=effective_uid,
            progress_callback=progress_callback,
        )
        if age_recipients_file is not None:
            artifact = encrypt_artifact(
                os.path.join(stage, artifact_name), artifact, age_recipients_file,
                age_executable=available.get("age"),
            )
            artifact_name = artifact.filename
        manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": image_id, "image_type": "partition",
            "source_size_bytes": size, "logical_sector_size": sector,
            "partition_table": "none", "artifacts": [artifact.to_dict()],
        })
        manifest_stage = os.path.join(stage, manifest_name)
        fd = os.open(manifest_stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(manifest.to_json())
            output.flush()
            os.fsync(output.fileno())
        signature_name = None
        if minisign_secret_key is not None:
            sign_manifest(manifest_stage, minisign_secret_key, minisign_executable=available.get("minisign"))
            signature_name = manifest_name + ".minisig"
        repository_fd = os.open(
            repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        publish_names = [artifact_name, manifest_name]
        if signature_name is not None:
            publish_names.append(signature_name)
        for name in publish_names:
            os.link(os.path.join(stage, name), name, dst_dir_fd=repository_fd, follow_symlinks=False)
            published.append(name)
        os.fsync(repository_fd)
        committed = True
        return manifest
    except CaptureCancelled:
        raise
    except (CaptureError, ManifestValidationError, OSError) as exc:
        raise PartitionImageCaptureError(f"partition image capture failed: {exc}") from exc
    finally:
        if not committed:
            for name in reversed(published):
                try:
                    if repository_fd is not None:
                        os.unlink(name, dir_fd=repository_fd)
                    else:
                        os.unlink(os.path.join(repo, name))
                except FileNotFoundError:
                    pass
        if repository_fd is not None:
            os.close(repository_fd)
        shutil.rmtree(stage, ignore_errors=True)
