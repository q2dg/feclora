"""Manifest-backed whole-disk capture using QCOW2 as the disk-image format."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from feclora.storage.artifact_writer import write_artifact
from feclora.storage.disk_capture import _parse_lsblk_geometry, _run_metadata
from feclora.storage.image_manifest import ImageArtifact, ImageManifest
from feclora.storage.image_publication import publish_image_set
from feclora.storage.p2v import P2VError, convert_block_device_to_qcow2
from feclora.storage.privilege import PrivilegeError, privileged_argv


class QCOW2CaptureError(RuntimeError):
    """A QCOW2 whole-disk image could not be captured safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_qcow2_disk(
    source_path: str,
    image_id: str,
    repository: str | os.PathLike[str],
    *,
    runner=subprocess.run,
) -> ImageManifest:
    """Capture an offline physical disk as a normal Feclora QCOW2 image set."""
    if not isinstance(image_id, str) or not image_id or len(image_id) > 128:
        raise QCOW2CaptureError("image_id must be a non-empty safe identifier")
    repo = Path(repository)
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise QCOW2CaptureError("image repository is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode) or stat.S_ISLNK(repo_info.st_mode):
        raise QCOW2CaptureError("image repository must be a real directory")
    names = [f"{image_id}.disk.qcow2", f"{image_id}.sfdisk", f"{image_id}.manifest.json"]
    if any(os.path.lexists(repo / name) for name in names):
        raise QCOW2CaptureError("image identifier already exists in the selected repository")

    stage = Path(tempfile.mkdtemp(prefix=".feclora-qcow2-", dir=repo))
    os.chmod(stage, 0o700)
    try:
        converted = convert_block_device_to_qcow2(source_path, stage / names[0], runner=runner)
        lsblk = shutil.which("lsblk")
        sfdisk = shutil.which("sfdisk")
        if not lsblk or not sfdisk:
            raise QCOW2CaptureError("lsblk and sfdisk are required for QCOW2 disk metadata")
        geometry = _run_metadata(
            [lsblk, "--bytes", "--noheadings", "--nodeps", "--output", "SIZE,LOG-SEC,PTTYPE", source_path],
            runner,
        )
        source_size, sector_size, table_type = _parse_lsblk_geometry(geometry)
        if (source_size != converted["virtual_size_bytes"]
                or sector_size != converted["logical_sector_size"]):
            raise QCOW2CaptureError("source disk geometry changed during QCOW2 capture")
        if table_type == "none":
            table_text = "# No partition table reported by lsblk; QCOW2 preserves all sectors.\\n"
        else:
            try:
                command = privileged_argv([sfdisk, "--dump", source_path])
            except PrivilegeError as exc:
                raise QCOW2CaptureError(f"cannot obtain root privileges for sfdisk: {exc}") from exc
            table_text = _run_metadata(command, runner)
            if not table_text.strip():
                raise QCOW2CaptureError("sfdisk returned an empty partition table")
        disk_path = stage / names[0]
        disk_info = os.lstat(disk_path)
        disk_artifact = ImageArtifact(
            filename=names[0], role="disk-image", format="qcow2", compression="none",
            size_bytes=disk_info.st_size, sha256=_sha256(disk_path),
        )
        table_artifact = write_artifact(
            stage, names[1], io.BytesIO(table_text.encode("utf-8")),
            role="partition-table", image_format="raw",
        )
        manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": image_id, "image_type": "disk",
            "source_size_bytes": source_size, "logical_sector_size": sector_size,
            "partition_table": table_type,
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
    except (P2VError, OSError, ValueError) as exc:
        raise QCOW2CaptureError(f"QCOW2 disk capture failed: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
