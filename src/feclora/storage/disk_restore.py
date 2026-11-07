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
from contextlib import contextmanager
from typing import Any, Callable
from .image_manifest import ImageArtifact, ImageManifest, ManifestValidationError
from .image_security import ImageSecurityError, decrypt_artifact_stream_to_temp, verify_manifest_signature
from .source_safety import SourceSafetyError, check_capture_source_safe
from .privilege import PrivilegeError, privileged_argv
from .compression import CompressionError, ExternalDecompressionStream

class DiskRestoreError(RuntimeError):
    """A whole-disk restore was rejected or failed."""


class DiskRestoreCancelled(DiskRestoreError):
    """The operator cancelled a running whole-disk restore."""

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


@contextmanager
def _verified_artifact_stream(repository: str, artifact: ImageArtifact,
                              age_identity_file: str | os.PathLike[str] | None,
                              age_executable: str | None):
    with _open_artifact(repository, artifact) as stored:
        _verify_stored_artifact(stored, artifact)
        if artifact.encryption == "none":
            yield stored
            return
        if artifact.encryption != "age":
            raise DiskRestoreError("unsupported image encryption")
        if not age_identity_file:
            raise DiskRestoreError("this image is age-encrypted; an identity file is required")
        try:
            staged = decrypt_artifact_stream_to_temp(
                stored, age_identity_file,
                repository, age_executable=age_executable,
            )
        except ImageSecurityError as exc:
            raise DiskRestoreError(f"image decryption/authentication failed: {exc}") from exc
        try:
            with open(staged, "rb") as plaintext:
                yield plaintext
        finally:
            try:
                os.unlink(staged)
            except FileNotFoundError:
                pass

def _decoded_stream(stream: Any, compression: str, executables: dict[str, str | None] | None = None):
    if compression == "none":
        return stream
    if compression == "gzip":
        return gzip.GzipFile(fileobj=stream, mode="rb")
    if compression == "xz":
        return lzma.LZMAFile(stream, mode="rb")
    if compression in {"zstd", "lz4"}:
        try:
            return ExternalDecompressionStream(stream, compression, executables)
        except CompressionError as exc:
            raise DiskRestoreError(str(exc)) from exc
    raise DiskRestoreError("unsupported restore compression")

def _preflight_decoded_size(stream: Any, artifact: ImageArtifact, expected: int, executables: dict[str, str | None] | None = None) -> None:
    decoded = _decoded_stream(stream, artifact.compression, executables)
    total = 0
    try:
        while True:
            chunk = decoded.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > expected:
                raise DiskRestoreError("decoded image exceeds manifest source size")
        if hasattr(decoded, "finish"):
            decoded.finish()
    except (OSError, EOFError, lzma.LZMAError, zlib.error, CompressionError) as exc:
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
            [lsblk, "--bytes", "--noheadings", "--nodeps", "--output", "SIZE,TYPE,LOG-SEC,RO", target_path],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiskRestoreError(f"cannot inspect target disk: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) != 4 or fields[1] != "disk":
        raise DiskRestoreError("restore target must be exactly one whole disk")
    try:
        size, sector_size = int(fields[0]), int(fields[2])
        read_only = fields[3] == "1"
    except ValueError as exc:
        raise DiskRestoreError("lsblk returned invalid target capacity") from exc
    if size <= 0 or sector_size not in {512, 4096} or read_only:
        raise DiskRestoreError("target disk geometry is invalid or read-only")
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
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    minisign_public_key: str | os.PathLike[str] | None = None,
    require_signature: bool = False,
    pre_write_callback: Callable[[], None] | None = None,
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
        initial_device_number = os.stat(target_path).st_rdev if device_validator is None else None
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

    signature_path = manifest_file + ".minisig"
    if require_signature and not os.path.isfile(signature_path):
        raise DiskRestoreError("a minisign signature is required but this image has none")
    if minisign_public_key is not None:
        if not os.path.isfile(signature_path):
            raise DiskRestoreError("minisign public key supplied but image signature is missing")
        try:
            verify_manifest_signature(manifest_file, minisign_public_key, signature_path=signature_path, minisign_executable=(executables or {}).get("minisign"))
        except ImageSecurityError as exc:
            raise DiskRestoreError(f"manifest signature verification failed: {exc}") from exc
    elif require_signature:
        raise DiskRestoreError("signature verification requires a trusted minisign public key")

    if manifest.image_type != "disk":
        raise DiskRestoreError("whole-disk restore requires a disk image manifest")
    disk_artifacts = [item for item in manifest.artifacts if item.role == "disk-image"]
    if len(disk_artifacts) != 1 or disk_artifacts[0].format != "raw":
        raise DiskRestoreError("manifest must contain exactly one raw disk-image artifact")
    artifact = disk_artifacts[0]
    if artifact.compression not in {"none", "gzip", "xz", "zstd", "lz4"}:
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

    with _verified_artifact_stream(repo, artifact, age_identity_file, available.get("age")) as image:
        _preflight_decoded_size(image, artifact, manifest.source_size_bytes, available)
        try:
            if not validator(target_path):
                raise DiskRestoreError("target device identity is no longer valid")
            safety(target_path)
        except SourceSafetyError as exc:
            raise DiskRestoreError(f"restore target became unsafe: {exc}") from exc

        decoded = _decoded_stream(image, artifact.compression, available)
        process = None
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        written = 0
        raw_digest = hashlib.sha256()
        try:
            if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
                raise DiskRestoreError("block-device identity changed before restore")
            if pre_write_callback is not None:
                # Call only after artifact, geometry, signature and safety
                # preflight has completed, immediately before the first write.
                pre_write_callback()
            factory = popen_factory or subprocess.Popen
            try:
                command = privileged_argv([dd, f"of={target_path}", "bs=4M", "conv=fsync", "status=none"], effective_uid=effective_uid)
                process = factory(
                    command,
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=stderr_file, close_fds=True,
                )
            except (OSError, PrivilegeError) as exc:
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
                        raw_digest.update(view[:count])
                        written += count
                        view = view[count:]
                    if progress_callback is not None:
                        progress_callback(written, manifest.source_size_bytes)
                if hasattr(decoded, "finish"):
                    decoded.finish()
                process.stdin.close()
            except (BrokenPipeError, OSError, EOFError, lzma.LZMAError, zlib.error, CompressionError) as exc:
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

            # Read the destination back and compare the exact restored byte range.
            try:
                if not validator(target_path):
                    raise DiskRestoreError("target device identity changed before read-back verification")
                safety(target_path)
                if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
                    raise DiskRestoreError("target block-device identity changed before read-back verification")
                verify_command = privileged_argv(
                    [dd, f"if={target_path}", "bs=4M", "iflag=count_bytes",
                     f"count={manifest.source_size_bytes}", "status=none"],
                    effective_uid=effective_uid,
                )
                verify_stderr = tempfile.TemporaryFile(mode="w+b")
                verify_process = None
                try:
                    verify_process = factory(
                        verify_command, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=verify_stderr, close_fds=True,
                    )
                    if verify_process.stdout is None:
                        raise DiskRestoreError("read-back dd did not provide an output pipe")
                    verify_digest = hashlib.sha256()
                    verify_size = 0
                    while True:
                        chunk = verify_process.stdout.read(1024 * 1024)
                        if not chunk:
                            break
                        verify_size += len(chunk)
                        verify_digest.update(chunk)
                    verify_process.stdout.close()
                    verify_return_code = verify_process.wait()
                    if verify_return_code != 0:
                        verify_stderr.seek(0)
                        detail = verify_stderr.read(8192).decode("utf-8", errors="replace").strip()
                        raise DiskRestoreError(
                            "read-back dd failed" + (f": {detail}" if detail else "")
                        )
                    if verify_size != manifest.source_size_bytes or verify_digest.digest() != raw_digest.digest():
                        raise DiskRestoreError("read-back verification failed: destination bytes differ from image")
                finally:
                    if verify_process is not None and verify_process.poll() is None:
                        verify_process.terminate()
                        verify_process.wait()
                    verify_stderr.close()
            except (OSError, PrivilegeError, SourceSafetyError) as exc:
                raise DiskRestoreError(f"read-back verification could not be completed: {exc}") from exc
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait()
            if decoded is not image:
                decoded.close()
            stderr_file.close()
    return manifest
