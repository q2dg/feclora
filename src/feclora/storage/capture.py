"""Read-only partition capture using generic Partclone or dd executables.

This module creates capture plans and streams producer stdout into the safe
artifact writer. It never restores data or opens a target block device.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Callable, Mapping

from .artifact_writer import ArtifactWriteError, write_artifact
from .image_manifest import ImageArtifact
from .source_safety import SourceSafetyError, check_capture_source_safe


class CaptureError(RuntimeError):
    """Raised when a partition capture cannot be completed safely."""


_FILESYSTEM_TO_PARTCLONE = {
    "btrfs": "partclone.btrfs",
    "ext2": "partclone.extfs",
    "ext3": "partclone.extfs",
    "ext4": "partclone.ext4",
    "exfat": "partclone.exfat",
    "fat": "partclone.fat",
    "fat12": "partclone.fat",
    "fat16": "partclone.fat",
    "fat32": "partclone.fat",
    "vfat": "partclone.fat",
    "f2fs": "partclone.f2fs",
    "ntfs": "partclone.ntfs",
    "xfs": "partclone.xfs",
}


@dataclass(frozen=True)
class CapturePlan:
    """A read-only command plan for one partition."""

    executable: str
    argv: tuple[str, ...]
    image_format: str
    filesystem: str | None


def build_capture_plan(
    source_path: str,
    filesystem: str | None,
    executables: Mapping[str, str | None] | None = None,
) -> CapturePlan:
    """Prefer filesystem-aware Partclone; explicitly fall back to raw dd."""
    if not isinstance(source_path, str) or not source_path.startswith("/dev/") or "\x00" in source_path:
        raise CaptureError("source must be an absolute /dev/ path")
    available = executables or {}
    fs = filesystem.lower() if isinstance(filesystem, str) and filesystem else None
    partclone_name = _FILESYSTEM_TO_PARTCLONE.get(fs) if fs else None
    partclone_path = available.get(partclone_name) if partclone_name else None
    if partclone_path:
        return CapturePlan(
            executable=partclone_path,
            argv=(partclone_path, "-c", "-s", source_path),
            image_format="partclone",
            filesystem=fs,
        )
    dd_path = available.get("dd") or shutil.which("dd")
    if not dd_path:
        raise CaptureError(
            f"No Partclone executable for filesystem {fs or 'unknown'} and dd is unavailable"
        )
    return CapturePlan(
        executable=dd_path,
        argv=(dd_path, f"if={source_path}", "bs=4M", "status=none"),
        image_format="raw",
        filesystem=fs,
    )


def _is_block_device(path: str) -> bool:
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def capture_partition(
    source_path: str,
    filesystem: str | None,
    repository: str | os.PathLike[str],
    filename: str,
    partition_id: str,
    executables: Mapping[str, str | None] | None = None,
    *,
    compression: str = "none",
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., subprocess.Popen] | None = None,
    source_safety_check: Callable[[str], None] | None = None,
) -> ImageArtifact:
    """Capture one block partition into a repository without overwriting files.

    The source is opened by the selected read-only imaging utility. By default
    it must resolve to a block device. A private staging directory prevents a
    failed producer process from publishing a partial artifact.
    """
    validator = device_validator or _is_block_device
    if not validator(source_path):
        raise CaptureError(f"source is not an accessible block device: {source_path}")
    try:
        (source_safety_check or check_capture_source_safe)(source_path)
    except SourceSafetyError as exc:
        raise CaptureError(f"unsafe capture source: {exc}") from exc
    plan = build_capture_plan(source_path, filesystem, executables)
    repository_path = os.fspath(repository)
    try:
        repo_info = os.lstat(repository_path)
    except OSError as exc:
        raise CaptureError("image repository directory is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode):
        raise CaptureError("image repository must be a real directory, not a symlink")

    stage_dir = tempfile.mkdtemp(prefix=".feclora-capture-", dir=repository_path)
    process = None
    artifact = None
    final_path = os.path.join(repository_path, filename)
    try:
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        try:
            factory = popen_factory or subprocess.Popen
            try:
                process = factory(
                    list(plan.argv),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=stderr_file,
                    close_fds=True,
                )
            except OSError as exc:
                raise CaptureError(f"could not start {plan.executable}: {exc}") from exc
            if process.stdout is None:
                raise CaptureError("capture process did not provide a stdout pipe")
            try:
                (source_safety_check or check_capture_source_safe)(source_path)
            except SourceSafetyError as exc:
                raise CaptureError(f"capture source became unsafe before imaging: {exc}") from exc
            try:
                artifact = write_artifact(
                    stage_dir,
                    filename,
                    process.stdout,
                    role="partition-image",
                    image_format=plan.image_format,
                    compression=compression,
                    partition_id=partition_id,
                    filesystem=plan.filesystem,
                )
            except ArtifactWriteError as exc:
                if process.poll() is None:
                    process.terminate()
                process.wait()
                raise CaptureError(f"could not store capture stream: {exc}") from exc
            finally:
                process.stdout.close()

            return_code = process.wait()
            if return_code != 0:
                stderr_file.seek(0)
                detail = stderr_file.read(8192).decode("utf-8", errors="replace").strip()
                raise CaptureError(
                    f"{plan.executable} exited with status {return_code}"
                    + (f": {detail}" if detail else "")
                )

            # Link is atomic and fails if the destination already exists.
            try:
                os.link(
                    os.path.join(stage_dir, filename),
                    final_path,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise CaptureError(f"artifact already exists: {filename}") from exc
            directory_fd = os.open(repository_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return artifact
        finally:
            stderr_file.close()
    except CaptureError:
        raise
    except OSError as exc:
        raise CaptureError(f"capture failed: {exc}") from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        shutil.rmtree(stage_dir, ignore_errors=True)
