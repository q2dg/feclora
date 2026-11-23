"""Finalize only fully rescued ddrescue jobs as normal disk image sets."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .ddrescue_recovery import (
    DdrescueRecoveryError, _load_state, _safe_workspace, parse_ddrescue_mapfile,
)
from .artifact_writer import ArtifactWriteError, write_artifact
from .image_manifest import ImageArtifact, ImageManifest, ManifestValidationError
from .image_publication import ImagePublicationError, publish_image_set


class RecoveryFinalizeError(RuntimeError):
    """A recovery job cannot be promoted to a restorable disk image."""


def _hash_regular_file(path: Path, expected_size: int) -> str:
    try:
        info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size != expected_size):
            raise RecoveryFinalizeError("recovered image is not a private regular file of the expected size")
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
        digest = hashlib.sha256()
        size = 0
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise RecoveryFinalizeError("recovered image changed while opening")
            os.fsync(fd)
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        finally:
            os.close(fd)
        if size != expected_size:
            raise RecoveryFinalizeError("recovered image size changed while hashing")
        return digest.hexdigest()
    except OSError as exc:
        raise RecoveryFinalizeError(f"cannot verify recovered image: {exc}") from exc


def _partition_table_text(
    image_path: Path,
    expected_type: str,
    executables: Mapping[str, str | None],
    runner: Callable[..., Any],
) -> tuple[str, str]:
    if expected_type == "none":
        return "none", "# No partition table reported by lsblk; raw disk image preserves all sectors.\n"
    sfdisk = executables.get("sfdisk") or shutil.which("sfdisk")
    if not sfdisk:
        raise RecoveryFinalizeError("sfdisk is required to finalize a disk with a partition table")
    try:
        result = runner(
            [sfdisk, "--dump", str(image_path)],
            check=False, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryFinalizeError(f"cannot inspect recovered partition table: {exc}") from exc
    if result.returncode != 0 or not isinstance(result.stdout, str) or not result.stdout.strip():
        raise RecoveryFinalizeError("sfdisk could not verify the recovered partition table")
    label = None
    for line in result.stdout.splitlines():
        if line.strip().startswith("label:"):
            label = line.split(":", 1)[1].strip().lower()
            break
    actual_type = {"gpt": "gpt", "dos": "mbr", "mbr": "mbr"}.get(label)
    if actual_type is None or (expected_type != "unknown" and actual_type != expected_type):
        raise RecoveryFinalizeError("recovered partition-table type does not match the source metadata")
    return actual_type, result.stdout.rstrip() + "\n"


def finalize_recovery_job(
    job_id: str,
    repository: str | os.PathLike[str],
    *,
    executables: Mapping[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
) -> ImageManifest:
    """Publish a manifest-backed raw disk image only after a complete mapfile."""
    try:
        workspace = _safe_workspace(repository, job_id, create=False)
        state = _load_state(workspace)
        if state.get("job_id") != job_id or state.get("state") != "completed":
            raise RecoveryFinalizeError("only a completed ddrescue job can be finalized")
        source_size = state.get("source_size_bytes")
        sector_size = state.get("logical_sector_size")
        table_type = state.get("partition_table")
        if (isinstance(source_size, bool) or not isinstance(source_size, int) or source_size <= 0
                or isinstance(sector_size, bool) or not isinstance(sector_size, int) or sector_size not in {512, 4096}
                or table_type not in {"gpt", "mbr", "none", "unknown"}):
            raise RecoveryFinalizeError("recovery job has incomplete or invalid source geometry")
        image_path = workspace / "recovered.img"
        mapfile_path = workspace / "recovery.map"
        summary = parse_ddrescue_mapfile(mapfile_path, source_size)
        if not summary.complete:
            raise RecoveryFinalizeError("ddrescue mapfile still contains unreadable or untried sectors")
        recorded = state.get("mapfile")
        if not isinstance(recorded, dict) or recorded.get("rescued_bytes") != source_size:
            raise RecoveryFinalizeError("recovery job metadata does not confirm full source recovery")
        digest = _hash_regular_file(image_path, source_size)
        available = executables or {}
        run = runner or subprocess.run
        table_type, table_text = _partition_table_text(image_path, table_type, available, run)
        repo = Path(os.path.abspath(os.fspath(repository)))
        stage = Path(tempfile.mkdtemp(prefix=".feclora-recovery-finalize-", dir=repo))
        try:
            image_name = f"{job_id}.disk.raw"
            table_name = f"{job_id}.sfdisk"
            manifest_name = f"{job_id}.manifest.json"
            os.link(image_path, stage / image_name, follow_symlinks=False)
            disk_artifact = ImageArtifact(
                filename=image_name, role="disk-image", format="raw",
                compression="none", size_bytes=source_size, sha256=digest,
            )
            table_artifact = write_artifact(
                stage, table_name, io.BytesIO(table_text.encode("utf-8")),
                role="partition-table", image_format="raw",
            )
            manifest = ImageManifest.from_dict({
                "schema_version": 1, "image_id": job_id, "image_type": "disk",
                "source_size_bytes": source_size, "logical_sector_size": sector_size,
                "partition_table": table_type,
                "artifacts": [disk_artifact.to_dict(), table_artifact.to_dict()],
            })
            manifest_path = stage / manifest_name
            fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(manifest.to_json())
                output.flush()
                os.fsync(output.fileno())
            publish_image_set(repo, stage, [image_name, table_name, manifest_name])
            return manifest
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    except RecoveryFinalizeError:
        raise
    except (DdrescueRecoveryError, ArtifactWriteError, ManifestValidationError,
            ImagePublicationError, FileExistsError, OSError) as exc:
        raise RecoveryFinalizeError(f"recovery finalization failed: {exc}") from exc
