"""Verified partition restore using Partclone or raw dd."""
from __future__ import annotations
import gzip
import hashlib
import lzma
import os
import shutil
import stat
import subprocess
import tempfile
import zlib
from typing import Any, Callable
from .image_manifest import ImageManifest, ManifestValidationError
from .source_safety import SourceSafetyError, check_capture_source_safe
from .privilege import PrivilegeError, privileged_argv

class PartitionRestoreError(RuntimeError):
    """A partition restore was rejected or failed."""

_PARTCLONE = {
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

def _safe_open(repository: str, filename: str):
    path = os.path.join(repository, filename)
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            raise PartitionRestoreError("partition image artifact must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise PartitionRestoreError(f"cannot safely open partition artifact: {exc}") from exc
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise PartitionRestoreError("partition artifact changed type while opening")
    return stream

def _verify_stored(stream: Any, artifact: Any) -> None:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
        raise PartitionRestoreError("partition artifact size or SHA-256 mismatch")
    stream.seek(0)

def _decompress_to_temp(source: Any, compression: str, expected_raw_size: int | None, directory: str):
    if compression == "none":
        decoder = source
    elif compression == "gzip":
        decoder = gzip.GzipFile(fileobj=source, mode="rb")
    elif compression == "xz":
        decoder = lzma.LZMAFile(source, mode="rb")
    else:
        raise PartitionRestoreError("partition restore supports none, gzip and xz compression")
    output = tempfile.TemporaryFile(mode="w+b", dir=directory)
    total = 0
    try:
        while True:
            chunk = decoder.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if expected_raw_size is not None and total > expected_raw_size:
                raise PartitionRestoreError("decoded raw image exceeds partition size in manifest")
            output.write(chunk)
        if total <= 0:
            raise PartitionRestoreError("decoded partition image is empty")
        if expected_raw_size is not None and total != expected_raw_size:
            raise PartitionRestoreError("decoded raw image size does not match manifest")
        output.flush()
        output.seek(0)
    except (OSError, EOFError, lzma.LZMAError, zlib.error) as exc:
        output.close()
        raise PartitionRestoreError(f"partition image decompression failed: {exc}") from exc
    finally:
        if decoder is not source:
            decoder.close()
    source.seek(0)
    return output, total

def _target_geometry(target: str, lsblk: str, runner: Callable[..., Any]) -> tuple[int, int]:
    try:
        result = runner(
            [lsblk, "--bytes", "--noheadings", "--nodeps", "--output", "SIZE,TYPE,LOG-SEC,RO", target],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PartitionRestoreError(f"cannot inspect target partition: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) != 4 or fields[1] != "part":
        raise PartitionRestoreError("restore target must be exactly one partition")
    try:
        size, sector_size = int(fields[0]), int(fields[2])
        read_only = fields[3] == "1"
    except ValueError as exc:
        raise PartitionRestoreError("lsblk returned invalid partition size") from exc
    if size <= 0 or sector_size not in {512, 4096} or read_only:
        raise PartitionRestoreError("target partition geometry is invalid or read-only")
    return size, sector_size

def restore_partition(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    target_path: str,
    *,
    confirmation: str,
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    target_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
) -> ImageManifest:
    """Restore one partition image; confirmation must be ERASE /dev/partition."""
    if not isinstance(target_path, str) or not target_path.startswith("/dev/"):
        raise PartitionRestoreError("target must be an absolute /dev/ path")
    if confirmation != f"ERASE {target_path}":
        raise PartitionRestoreError(f"explicit confirmation required: ERASE {target_path}")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(target_path):
            raise PartitionRestoreError("target is not an accessible block device")
        initial_device_number = os.stat(target_path).st_rdev if device_validator is None else None
    except OSError as exc:
        raise PartitionRestoreError(f"cannot inspect target block device: {exc}") from exc
    repo = os.path.abspath(os.fspath(repository))
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode):
            raise PartitionRestoreError("image repository must be a real directory")
        manifest_file = os.fspath(manifest_path)
        if not os.path.isabs(manifest_file):
            manifest_file = os.path.join(repo, manifest_file)
        fd = os.open(manifest_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise PartitionRestoreError("manifest must be a regular file")
            manifest = ImageManifest.from_json(source.read())
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise PartitionRestoreError(f"cannot load valid partition manifest: {exc}") from exc
    if manifest.image_type != "partition":
        raise PartitionRestoreError("partition restore requires a partition image manifest")
    artifacts = [item for item in manifest.artifacts if item.role == "partition-image"]
    if len(artifacts) != 1:
        raise PartitionRestoreError("manifest must contain exactly one partition-image artifact")
    artifact = artifacts[0]
    available = executables or {}
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    if not lsblk:
        raise PartitionRestoreError("lsblk is required for partition restore")
    run = runner or subprocess.run
    target_size, target_sector_size = _target_geometry(target_path, lsblk, run)
    if target_sector_size != manifest.logical_sector_size:
        raise PartitionRestoreError("target logical sector size differs from the image")
    if target_size < manifest.source_size_bytes:
        raise PartitionRestoreError("target partition is smaller than the source partition")
    if artifact.format == "partclone":
        partclone_name = _PARTCLONE.get(artifact.filesystem or "")
        executable = available.get(partclone_name) if partclone_name else None
        executable = executable or (shutil.which(partclone_name) if partclone_name else None)
        if not executable:
            raise PartitionRestoreError(
                f"Partclone restore utility is unavailable for filesystem {artifact.filesystem!r}"
            )
    else:
        executable = available.get("dd") or shutil.which("dd")
        if not executable:
            raise PartitionRestoreError("dd is required for raw partition restore")
    safety = target_safety_check or check_capture_source_safe
    try:
        safety(target_path)
    except SourceSafetyError as exc:
        raise PartitionRestoreError(f"unsafe restore target: {exc}") from exc

    with _safe_open(repo, artifact.filename) as image:
        _verify_stored(image, artifact)
        staged, decoded_size = _decompress_to_temp(
            image, artifact.compression,
            manifest.source_size_bytes if artifact.format == "raw" else None,
            repo,
        )
        try:
            # Validate the block-device role and safety again immediately before
            # starting the destructive process.
            if not validator(target_path):
                raise PartitionRestoreError("target block-device identity changed")
            refreshed_size, refreshed_sector = _target_geometry(target_path, lsblk, run)
            if refreshed_size < manifest.source_size_bytes or refreshed_sector != manifest.logical_sector_size:
                raise PartitionRestoreError("target partition geometry changed")
            try:
                safety(target_path)
            except SourceSafetyError as exc:
                raise PartitionRestoreError(f"restore target became unsafe: {exc}") from exc
            if artifact.format == "partclone":
                argv = [executable, "-r", "-s", f"/proc/self/fd/{staged.fileno()}", "-o", target_path]
                extra = {"pass_fds": (staged.fileno(),)}
                # The child receives the staged, fully verified decompressed
                # stream through an inherited descriptor, not an untrusted path.
                stdin = subprocess.DEVNULL
            else:
                argv = [executable, f"of={target_path}", "bs=4M", "conv=fsync", "status=none"]
                extra = {}
                staged.seek(0)
                stdin = staged
            stderr = tempfile.TemporaryFile(mode="w+b")
            process = None
            try:
                if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
                    raise PartitionRestoreError("block-device identity changed before restore")
                factory = popen_factory or subprocess.Popen
                try:
                    command = privileged_argv(argv, effective_uid=effective_uid)
                    process = factory(
                        command, stdin=stdin, stdout=subprocess.DEVNULL,
                        stderr=stderr, close_fds=True, **extra,
                    )
                except (OSError, PrivilegeError) as exc:
                    raise PartitionRestoreError(f"could not start restore utility: {exc}") from exc
                return_code = process.wait()
                if return_code != 0:
                    stderr.seek(0)
                    detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
                    raise PartitionRestoreError(
                        f"restore utility exited with status {return_code}" +
                        (f": {detail}" if detail else "")
                    )
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait()
                stderr.close()
        finally:
            staged.close()
    return manifest
