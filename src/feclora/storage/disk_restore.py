"""Verified whole-disk restore using generic dd and standard decompressors."""
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
from .image_manifest import ImageArtifact, ImageManifest, ManifestValidationError
from .source_safety import SourceSafetyError, check_capture_source_safe

class DiskRestoreError(RuntimeError):
    """A whole-disk restore was rejected or failed."""

def _open_artifact(repository: str, artifact: ImageArtifact):
    path = os.path.join(repository, artifact.filename)
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            raise DiskRestoreError("image artifact must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise DiskRestoreError(f"cannot safely open image artifact: {exc}") from exc
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise DiskRestoreError("image artifact changed type while opening")
    return stream

def _verify_stored_artifact(stream: Any, artifact: ImageArtifact) -> None:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    if size != artifact.size_bytes:
        raise DiskRestoreError("stored artifact size does not match manifest")
    if digest.hexdigest() != artifact.sha256:
        raise DiskRestoreError("artifact SHA-256 does not match manifest")
    stream.seek(0)

def _decoded_stream(stream: Any, compression: str):
    if compression == "none":
        return stream
    if compression == "gzip":
        return gzip.GzipFile(fileobj=stream, mode="rb")
    if compression == "xz":
        return lzma.LZMAFile(stream, mode="rb")
    raise DiskRestoreError("restore currently supports only none, gzip and xz")

def _preflight_decoded_size(stream: Any, artifact: ImageArtifact, expected: int) -> None:
    decoded = _decoded_stream(stream, artifact.compression)
    total = 0
    try:
        while True:
            chunk = decoded.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > expected:
                raise DiskRestoreError("decoded image exceeds manifest source size")
    except (OSError, EOFError, lzma.LZMAError, zlib.error) as exc:
        raise DiskRestoreError(f"image decompression preflight failed: {exc}") from exc
    finally:
        if decoded is not stream:
            decoded.close()
    if total != expected:
        raise DiskRestoreError("decoded image size does not match manifest source size")
    stream.seek(0)

def _target_geometry(target_path: str, lsblk: str, runner: Callable[..., Any]) -> tuple[int, int]:
    try:
        result = runner(
            [lsblk, "--bytes", "--noheadings", "--nodeps", "--output", "SIZE,TYPE,LOG-SEC", target_path],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiskRestoreError(f"cannot inspect target disk: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) != 3 or fields[1] != "disk":
        raise DiskRestoreError("restore target must be exactly one whole disk")
    try:
        size, sector_size = int(fields[0]), int(fields[2])
    except ValueError as exc:
        raise DiskRestoreError("lsblk returned invalid target capacity") from exc
    if size <= 0 or sector_size not in {512, 4096}:
        raise DiskRestoreError("target disk geometry is invalid")
    return size, sector_size

def restore_disk(
    manifest_path: str | os.PathLike[str],
    repository: str | os.PathLike[str],
    target_path: str,
    *,
    confirmation: str,
    executables: dict[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    runner: Callable[..., Any] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    target_safety_check: Callable[[str], None] | None = None,
) -> ImageManifest:
    """Restore a verified raw whole-disk image to a whole-disk block device.

    confirmation must equal the exact phrase ERASE followed by target_path.
    """
    if not isinstance(target_path, str) or not target_path.startswith("/dev/"):
        raise DiskRestoreError("target must be an absolute /dev/ path")
    if confirmation != f"ERASE {target_path}":
        raise DiskRestoreError(f"explicit confirmation required: ERASE {target_path}")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(target_path):
            raise DiskRestoreError(f"target is not an accessible block device: {target_path}")
    except OSError as exc:
        raise DiskRestoreError(f"cannot inspect target device: {exc}") from exc

    repo = os.path.abspath(os.fspath(repository))
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise DiskRestoreError("image repository is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode):
        raise DiskRestoreError("image repository must be a real directory, not a symlink")
    manifest_file = os.fspath(manifest_path)
    if not os.path.isabs(manifest_file):
        manifest_file = os.path.join(repo, manifest_file)
    try:
        fd = os.open(manifest_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise DiskRestoreError("manifest must be a regular file, not a symlink")
            manifest = ImageManifest.from_json(source.read())
    except (OSError, UnicodeError, ManifestValidationError) as exc:
        raise DiskRestoreError(f"cannot load valid image manifest: {exc}") from exc

    if manifest.image_type != "disk":
        raise DiskRestoreError("whole-disk restore requires a disk image manifest")
    disk_artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(disk_artifacts) != 1 or disk_artifacts[0].format != "raw":
        raise DiskRestoreError("manifest must contain exactly one raw disk-image artifact")
    artifact = disk_artifacts[0]
    if artifact.compression not in {"none", "gzip", "xz"}:
        raise DiskRestoreError("unsupported restore compression")
    available = executables or {}
    dd = available.get("dd") or shutil.which("dd")
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    if not dd or not lsblk:
        raise DiskRestoreError("dd and lsblk are required for whole-disk restore")
    run = runner or subprocess.run
    target_size, target_sector_size = _target_geometry(target_path, lsblk, run)
    if target_sector_size != manifest.logical_sector_size:
        raise DiskRestoreError("target logical sector size differs from the image")
    if target_size < manifest.source_size_bytes:
        raise DiskRestoreError("target disk is smaller than the source image")
    safety = target_safety_check or check_capture_source_safe
    try:
        safety(target_path)
    except SourceSafetyError as exc:
        raise DiskRestoreError(f"unsafe restore target: {exc}") from exc

    with _open_artifact(repo, artifact) as image:
        _verify_stored_artifact(image, artifact)
        _preflight_decoded_size(image, artifact, manifest.source_size_bytes)
        try:
            if not validator(target_path):
                raise DiskRestoreError("target device identity is no longer valid")
            safety(target_path)
        except SourceSafetyError as exc:
            raise DiskRestoreError(f"restore target became unsafe: {exc}") from exc

        decoded = _decoded_stream(image, artifact.compression)
        process = None
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        written = 0
        try:
            factory = popen_factory or subprocess.Popen
            try:
                process = factory(
                    [dd, f"of={target_path}", "bs=4M", "conv=fsync", "status=none"],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=stderr_file, close_fds=True,
                )
            except OSError as exc:
                raise DiskRestoreError(f"could not start dd: {exc}") from exc
            if process.stdin is None:
                raise DiskRestoreError("dd did not provide a writable input pipe")
            try:
                while True:
                    chunk = decoded.read(1024 * 1024)
                    if not chunk:
                        break
                    view = memoryview(chunk)
                    while view:
                        count = process.stdin.write(view)
                        if count is None or count <= 0:
                            raise DiskRestoreError("dd input pipe stopped accepting data")
                        written += count
                        view = view[count:]
                process.stdin.close()
            except (BrokenPipeError, OSError, EOFError, lzma.LZMAError, zlib.error) as exc:
                if process.poll() is None:
                    process.terminate()
                process.wait()
                raise DiskRestoreError(f"failed while streaming image to dd: {exc}") from exc
            return_code = process.wait()
            if return_code != 0:
                stderr_file.seek(0)
                detail = stderr_file.read(8192).decode("utf-8", errors="replace").strip()
                raise DiskRestoreError(f"dd exited with status {return_code}" + (f": {detail}" if detail else ""))
            if written != manifest.source_size_bytes:
                raise DiskRestoreError("dd accepted a byte count different from manifest source size")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait()
            if decoded is not image:
                decoded.close()
            stderr_file.close()
    return manifest
