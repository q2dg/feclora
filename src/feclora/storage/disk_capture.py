"""Transactional, read-only whole-disk capture using dd and sfdisk."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Mapping

from .artifact_writer import ArtifactWriteError, write_artifact
from .capture import CaptureError, _is_block_device
from .image_manifest import ImageArtifact, ImageManifest, ManifestValidationError
from .source_safety import SourceSafetyError, check_capture_source_safe


class _CountingReader:
    def __init__(self, stream):
        self.stream = stream
        self.bytes_read = 0
    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.bytes_read += len(chunk)
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
    executables: Mapping[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    popen_factory: Callable[..., subprocess.Popen] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
) -> ImageManifest:
    """Capture a complete disk as raw bytes plus sfdisk metadata.

    All outputs are staged first. Artifacts are published without replacement,
    and the manifest is published last as the image-set commit marker.
    """
    if not isinstance(image_id, str) or not image_id or len(image_id) > 128:
        raise DiskCaptureError("image_id must be a non-empty safe identifier")
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
    table_text = _run_metadata([sfdisk, "--dump", source_path], run)
    if not table_text.strip():
        table_text = "# No partition table reported by sfdisk; raw disk image preserves all sectors.\n"

    disk_suffix = {"none": ".raw", "gzip": ".raw.gz", "xz": ".raw.xz"}.get(compression)
    if disk_suffix is None:
        raise DiskCaptureError("compression must be none, gzip or xz")
    disk_filename = image_id + ".disk" + disk_suffix
    table_filename = image_id + ".sfdisk"
    manifest_filename = image_id + ".manifest.json"
    stage = tempfile.mkdtemp(prefix=".feclora-disk-", dir=repo)
    process = None
    published: list[str] = []
    committed = False
    repository_fd = None
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
                process = factory(
                    [dd, f"if={source_path}", "bs=4M", "status=none"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=stderr_file, close_fds=True,
                )
            except OSError as exc:
                raise DiskCaptureError(f"could not start dd: {exc}") from exc
            if process.stdout is None:
                raise DiskCaptureError("dd did not provide a stdout pipe")
            counted = _CountingReader(process.stdout)
            try:
                disk_artifact = write_artifact(
                    stage, disk_filename, counted,
                    role="disk-image", image_format="raw", compression=compression,
                )
            except ArtifactWriteError as exc:
                if process.poll() is None:
                    process.terminate()
                process.wait()
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
            process = None

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

        # Publish payload files first and manifest last. Roll back all names
        # created by this transaction if any publication step fails.
        repository_fd = os.open(
            repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        for name in (table_filename, disk_filename, manifest_filename):
            try:
                os.link(
                    os.path.join(stage, name), name,
                    dst_dir_fd=repository_fd, follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise DiskCaptureError(f"image artifact already exists: {name}") from exc
            published.append(name)
        os.fsync(repository_fd)
        committed = True
        return manifest
    except (ArtifactWriteError, ManifestValidationError, OSError) as exc:
        raise DiskCaptureError(f"whole-disk capture failed: {exc}") from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        if published and not committed:
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
