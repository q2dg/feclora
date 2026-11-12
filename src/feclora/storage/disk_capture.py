"""Transactional, read-only whole-disk capture using dd and sfdisk."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from .process_control import stop_process
from pathlib import Path
from typing import Callable, Mapping

from .artifact_writer import ArtifactWriteError, write_artifact
from .capture import CaptureError, _is_block_device
from .image_manifest import ImageArtifact, ImageManifest, ManifestValidationError
from .image_publication import ImagePublicationError, publish_image_set
from .image_security import ImageSecurityError, encrypt_artifact, encrypt_artifact_with_passphrase, preflight_image_security
from .source_safety import SourceSafetyError, check_capture_source_safe
from .privilege import PrivilegeError, privileged_argv


class _CountingReader:
    def __init__(self, stream, progress_callback=None, expected_size_bytes=None):
        self.stream = stream
        self.bytes_read = 0
        self.progress_callback = progress_callback
        self.expected_size_bytes = expected_size_bytes
    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.bytes_read += len(chunk)
        if chunk and self.progress_callback is not None:
            self.progress_callback(self.bytes_read, self.expected_size_bytes)
        return chunk


class DiskCaptureError(RuntimeError):
    """Raised when a whole-disk image cannot be safely committed."""


def _run_metadata(command: list[str], runner: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    try:
        result = runner(
            command, check=True, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiskCaptureError(f"metadata command failed ({command[0]}): {exc}") from exc
    return result.stdout


def _parse_lsblk_geometry(output: str) -> tuple[int, int, str]:
    fields = output.split()
    if len(fields) < 2:
        raise DiskCaptureError("lsblk did not return disk size and logical sector size")
    try:
        size_bytes, sector_size = int(fields[0]), int(fields[1])
    except ValueError as exc:
        raise DiskCaptureError("lsblk returned invalid disk geometry") from exc
    if size_bytes <= 0 or sector_size not in {512, 4096}:
        raise DiskCaptureError("disk geometry is unsupported or invalid")
    pttype = fields[2].lower() if len(fields) > 2 else ""
    table = {"gpt": "gpt", "dos": "mbr", "mbr": "mbr", "": "none"}.get(pttype, "unknown")
    return size_bytes, sector_size, table


def capture_disk(
    source_path: str,
    image_id: str,
    repository: str | os.PathLike[str],
    *,
    compression: str = "none",
    compression_level: int | None = None,
    executables: Mapping[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    popen_factory: Callable[..., subprocess.Popen] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
    age_recipients_file: str | os.PathLike[str] | None = None,
    age_passphrase: str | None = None,
) -> ImageManifest:
    """Capture a complete disk as raw bytes plus sfdisk metadata.

    All outputs are staged first. Artifacts are published without replacement,
    and the manifest is published last as the image-set commit marker.
    """
    if not isinstance(image_id, str) or not image_id or len(image_id) > 128:
        raise DiskCaptureError("image_id must be a non-empty safe identifier")
    if age_recipients_file is not None and age_passphrase is not None:
        raise DiskCaptureError("choose either age recipients or a symmetric passphrase, not both")
    try:
        # Reuse the manifest's identifier validator as the canonical contract.
        ImageManifest.from_dict({
            "schema_version": 1, "image_id": image_id, "image_type": "disk",
            "source_size_bytes": 1, "logical_sector_size": 512,
            "partition_table": "none",
            "artifacts": [{
                "filename": "disk.raw", "role": "disk-image", "format": "raw",
                "compression": "none", "size_bytes": 1, "sha256": "0" * 64,
            }, {
                "filename": "table.txt", "role": "partition-table", "format": "raw",
                "compression": "none", "size_bytes": 1, "sha256": "0" * 64,
            }],
        })
    except ManifestValidationError as exc:
        raise DiskCaptureError(f"invalid image_id: {exc}") from exc

    validator = device_validator or _is_block_device
    if not validator(source_path):
        raise DiskCaptureError(f"source is not an accessible block device: {source_path}")
    initial_device_number = os.stat(source_path).st_rdev if device_validator is None else None
    try:
        (source_safety_check or check_capture_source_safe)(source_path)
    except SourceSafetyError as exc:
        raise DiskCaptureError(f"unsafe capture source: {exc}") from exc
    available = executables or {}
    try:
        preflight_image_security(
            age_recipients_file=age_recipients_file,
            age_executable=available.get("age"),
        )
    except ImageSecurityError as exc:
        raise DiskCaptureError(f"image security preflight failed: {exc}") from exc
    dd = available.get("dd") or shutil.which("dd")
    sfdisk = available.get("sfdisk") or shutil.which("sfdisk")
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    if not dd or not sfdisk or not lsblk:
        raise DiskCaptureError("dd, sfdisk and lsblk are required for whole-disk capture")

    repo = os.fspath(repository)
    try:
        info = os.lstat(repo)
    except OSError as exc:
        raise DiskCaptureError("image repository is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise DiskCaptureError("image repository must be a real directory, not a symlink")

    run = runner or subprocess.run
    geometry = _run_metadata(
        [lsblk, "--bytes", "--noheadings", "--nodeps", "--output", "SIZE,LOG-SEC,PTTYPE", source_path],
        run,
    )
    source_size, sector_size, table_type = _parse_lsblk_geometry(geometry)
    if table_type == "none":
        table_text = "# No partition table reported by lsblk; raw disk image preserves all sectors.\n"
    else:
        try:
            sfdisk_command = privileged_argv([sfdisk, "--dump", source_path], effective_uid=effective_uid)
        except PrivilegeError as exc:
            raise DiskCaptureError(f"cannot obtain root privileges for sfdisk: {exc}") from exc
        table_text = _run_metadata(sfdisk_command, run)
        if not table_text.strip():
            table_text = "# No partition table reported by sfdisk; raw disk image preserves all sectors.\n"

    disk_suffix = {
        "none": ".raw", "gzip": ".raw.gz", "xz": ".raw.xz",
        "zstd": ".raw.zst", "lz4": ".raw.lz4",
    }.get(compression)
    if disk_suffix is None:
        raise DiskCaptureError("compression must be none, gzip, xz, zstd or lz4")
    disk_filename = image_id + ".disk" + disk_suffix
    table_filename = image_id + ".sfdisk"
    manifest_filename = image_id + ".manifest.json"
    stage = tempfile.mkdtemp(prefix=".feclora-disk-", dir=repo)
    process = None
    try:
        table_artifact = write_artifact(
            stage, table_filename, __import__("io").BytesIO(table_text.encode("utf-8")),
            role="partition-table", image_format="raw",
        )
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        try:
            try:
                (source_safety_check or check_capture_source_safe)(source_path)
            except SourceSafetyError as exc:
                raise DiskCaptureError(f"capture source became unsafe before dd: {exc}") from exc
            if initial_device_number is not None and os.stat(source_path).st_rdev != initial_device_number:
                raise DiskCaptureError("block-device identity changed before imaging")
            factory = popen_factory or subprocess.Popen
            try:
                command = privileged_argv([dd, f"if={source_path}", "bs=4M", "status=none"], effective_uid=effective_uid)
                process = factory(
                    command,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=stderr_file, close_fds=True,
                )
            except (OSError, PrivilegeError) as exc:
                raise DiskCaptureError(f"could not start dd: {exc}") from exc
            if process.stdout is None:
                raise DiskCaptureError("dd did not provide a stdout pipe")
            counted = _CountingReader(process.stdout, progress_callback, source_size)
            try:
                disk_artifact = write_artifact(
                    stage, disk_filename, counted,
                    role="disk-image", image_format="raw", compression=compression,
                    compression_level=compression_level,
                    compression_executable=available.get(compression),
                )
                if age_recipients_file is not None:
                    disk_artifact = encrypt_artifact(
                        os.path.join(stage, disk_filename), disk_artifact,
                        age_recipients_file, age_executable=available.get("age"),
                    )
                    disk_filename = disk_artifact.filename
                elif age_passphrase is not None:
                    disk_artifact = encrypt_artifact_with_passphrase(
                        os.path.join(stage, disk_filename), disk_artifact,
                        age_passphrase, age_executable=available.get("age"),
                    )
                    disk_filename = disk_artifact.filename
            except ArtifactWriteError as exc:
                stop_process(process)
                raise DiskCaptureError(f"could not store disk stream: {exc}") from exc
            finally:
                process.stdout.close()
            return_code = process.wait()
            if return_code != 0:
                stderr_file.seek(0)
                detail = stderr_file.read(8192).decode("utf-8", errors="replace").strip()
                raise DiskCaptureError(
                    f"dd exited with status {return_code}" + (f": {detail}" if detail else "")
                )
        finally:
            stderr_file.close()

        if counted.bytes_read != source_size:
            raise DiskCaptureError(
                f"whole-disk capture size mismatch: expected {source_size}, read {counted.bytes_read}"
            )
        manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": image_id,
            "image_type": "disk",
            "source_size_bytes": source_size,
            "logical_sector_size": sector_size,
            "partition_table": table_type,
            "artifacts": [disk_artifact.to_dict(), table_artifact.to_dict()],
        })
        manifest_temp = os.path.join(stage, manifest_filename)
        fd = os.open(manifest_temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(manifest.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        signature_filename = None
        publish_names = [table_filename, disk_filename]
        if signature_filename is not None:
            publish_names.append(signature_filename)
        publish_names.append(manifest_filename)
        try:
            publish_image_set(repo, stage, publish_names)
        except FileExistsError as exc:
            raise DiskCaptureError(f"image artifact already exists: {exc.filename or 'publication target'}") from exc
        except ImagePublicationError as exc:
            raise DiskCaptureError(str(exc)) from exc
        return manifest
    except (ArtifactWriteError, ImageSecurityError, ManifestValidationError, OSError) as exc:
        raise DiskCaptureError(f"whole-disk capture failed: {exc}") from exc
    finally:
        stop_process(process)
        shutil.rmtree(stage, ignore_errors=True)
