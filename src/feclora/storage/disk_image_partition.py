"""Extract one validated partition from a verified whole-disk image."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Callable

from .artifact_writer import ArtifactWriteError, write_artifact
from .disk_restore import (
    DiskRestoreError,
    _decoded_stream,
    _open_artifact,
    _preflight_decoded_size,
    _verified_artifact_stream,
    _verify_stored_artifact,
)
from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import ImageSecurityError, encrypt_artifact
from .partition_range import PartitionRangeError, parse_sfdisk_dump, select_partition_range


class DiskImagePartitionError(RuntimeError):
    """A partition could not be safely extracted from a disk image."""


def _load_manifest(path: str, repository: str) -> ImageManifest:
    manifest_path = path if os.path.isabs(path) else os.path.join(repository, path)
    try:
        fd = os.open(manifest_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise DiskImagePartitionError("manifest must be a regular file")
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise DiskImagePartitionError("manifest exceeds 1 MiB")
        manifest = ImageManifest.from_json(raw.decode("utf-8"))
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise DiskImagePartitionError(f"cannot load disk image manifest: {exc}") from exc
    return manifest


def extract_partition_image(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    selector: str,
    *,
    age_identity_file: str | os.PathLike[str] | None = None,
    age_recipients_file: str | os.PathLike[str] | None = None,
    executables: dict[str, str | None] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[ImageManifest, str]:
    """Extract one raw partition image and publish its manifest last.

    The source disk artifact is authenticated/decrypted and decompressed using
    the same verified streaming path as whole-disk restore. The extracted image
    is an ordinary raw partition image that can be passed to restore_partition.
    """
    repo = os.path.abspath(os.fspath(repository))
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode):
            raise DiskImagePartitionError("image repository must be a real directory")
    except OSError as exc:
        raise DiskImagePartitionError("image repository is unavailable") from exc

    supplied_manifest = os.fspath(manifest_path)
    manifest_file = supplied_manifest if os.path.isabs(supplied_manifest) else os.path.join(repo, supplied_manifest)
    manifest = _load_manifest(manifest_file, repo)
    if manifest.image_type != "disk":
        raise DiskImagePartitionError("partition extraction requires a whole-disk image")
    disk_artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
    table_artifacts = [item for item in manifest.artifacts if item.role == "partition-table"]
    if len(disk_artifacts) != 1 or disk_artifacts[0].format != "raw":
        raise DiskImagePartitionError("manifest must contain exactly one raw disk-image artifact")
    if len(table_artifacts) != 1 or table_artifacts[0].format != "raw":
        raise DiskImagePartitionError("manifest must contain exactly one raw partition-table artifact")

    table_artifact = table_artifacts[0]
    if table_artifact.encryption != "none" or table_artifact.compression != "none":
        raise DiskImagePartitionError("partition-table metadata must be stored unencrypted and uncompressed")
    try:
        with _open_artifact(repo, table_artifact) as table_stream:
            _verify_stored_artifact(table_stream, table_artifact)
            table_raw = table_stream.read(1024 * 1024 + 1)
    except DiskRestoreError as exc:
        raise DiskImagePartitionError(
            f"partition-table artifact verification failed: {exc}"
        ) from exc
    if len(table_raw) > 1024 * 1024:
        raise DiskImagePartitionError("partition-table metadata exceeds 1 MiB")
    try:
        table = parse_sfdisk_dump(
            table_raw.decode("utf-8"),
            image_size_bytes=manifest.source_size_bytes,
            default_sector_size=manifest.logical_sector_size,
        )
        selected = select_partition_range(
            table, selector, image_size_bytes=manifest.source_size_bytes,
            sector_size=manifest.logical_sector_size,
        )
    except (UnicodeError, PartitionRangeError) as exc:
        raise DiskImagePartitionError(f"partition table or selector is invalid: {exc}") from exc

    artifact = disk_artifacts[0]
    stage = tempfile.mkdtemp(prefix=".feclora-extract-", dir=repo)
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]", "-", manifest.image_id)[:72]
    artifact_name = f"{safe_prefix}.partition-{uuid.uuid4().hex}.raw"
    manifest_name = artifact_name + ".manifest.json"
    published: list[str] = []
    directory_fd = None
    try:
        with _verified_artifact_stream(
            repo, artifact, age_identity_file, (executables or {}).get("age")
        ) as stored:
            _preflight_decoded_size(stored, artifact, manifest.source_size_bytes, executables)
            decoded = _decoded_stream(stored, artifact.compression, executables)
            try:
                remaining = selected.offset_bytes
                while remaining:
                    chunk = decoded.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise DiskImagePartitionError("disk image ended before selected partition offset")
                    remaining -= len(chunk)
                class ExactRange:
                    def __init__(self):
                        self.remaining = selected.length_bytes
                        self.copied = 0
                    def read(self, size=-1):
                        if self.remaining <= 0:
                            return b""
                        amount = self.remaining if size is None or size < 0 else min(size, self.remaining)
                        chunk = decoded.read(amount)
                        if not chunk:
                            raise DiskImagePartitionError("disk image ended inside selected partition")
                        self.remaining -= len(chunk)
                        self.copied += len(chunk)
                        if progress_callback is not None:
                            progress_callback(self.copied, selected.length_bytes)
                        return chunk
                exact = ExactRange()
                image_artifact = write_artifact(
                    stage, artifact_name, exact, role="partition-image",
                    image_format="raw", partition_id=(re.sub(r"[^A-Za-z0-9_.+-]", "-", Path(selected.node).name)[:64] or "partition"),
                )
                if exact.remaining:
                    raise DiskImagePartitionError("partition extraction did not consume the complete range")
                if hasattr(decoded, "finish"):
                    decoded.finish()
            finally:
                if decoded is not stored:
                    decoded.close()

        if age_recipients_file is not None:
            image_artifact = encrypt_artifact(
                os.path.join(stage, artifact_name), image_artifact, age_recipients_file,
                age_executable=(executables or {}).get("age"),
            )
            artifact_name = image_artifact.filename
        extracted_manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": f"{safe_prefix}-part-{uuid.uuid4().hex[:12]}"[:128],
            "image_type": "partition",
            "source_size_bytes": selected.length_bytes,
            "logical_sector_size": manifest.logical_sector_size,
            "partition_table": "none",
            "artifacts": [image_artifact.to_dict()],
        })
        staged_manifest = os.path.join(stage, manifest_name)
        fd = os.open(staged_manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(extracted_manifest.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        from .image_publication import publish_image_set
        publish_image_set(repo, stage, [artifact_name, manifest_name])
        return extracted_manifest, manifest_name
    except (ArtifactWriteError, DiskRestoreError, ImageSecurityError, OSError, ManifestValidationError) as exc:
        for name in reversed(published):
            try:
                if directory_fd is not None:
                    os.unlink(name, dir_fd=directory_fd)
                else:
                    os.unlink(os.path.join(repo, name))
            except FileNotFoundError:
                pass
        raise DiskImagePartitionError(f"partition extraction failed: {exc}") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        import shutil
        shutil.rmtree(stage, ignore_errors=True)
