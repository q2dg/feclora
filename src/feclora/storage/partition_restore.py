"""Verified partition restore using Partclone or raw dd."""
from __future__ import annotations
import gzip
import hashlib
import lzma
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zlib
from contextlib import contextmanager
from typing import Any, Callable
from .image_manifest import ImageManifest, ManifestValidationError
from .image_security import ImageSecurityError, decrypt_artifact_stream_to_temp, verify_manifest_signature
from .source_safety import SourceSafetyError, check_capture_source_safe
from .privilege import PrivilegeError, privileged_argv
from .compression import CompressionError, ExternalDecompressionStream
from .capture import _partclone_supports_json_status, _read_partclone_status, _partclone_stderr_progress
from .process_control import stop_process

class PartitionRestoreError(RuntimeError):
    """A partition restore was rejected or failed."""


class PartitionRestoreCancelled(PartitionRestoreError):
    """The operator cancelled a partition restore."""

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


@contextmanager
def _verified_artifact_stream(repository: str, artifact: Any,
                              age_identity_file: str | os.PathLike[str] | None,
                              age_executable: str | None):
    with _safe_open(repository, artifact.filename) as stored:
        _verify_stored(stored, artifact)
        if artifact.encryption == "none":
            yield stored
            return
        if artifact.encryption != "age":
            raise PartitionRestoreError("unsupported image encryption")
        if not age_identity_file:
            raise PartitionRestoreError("this image is age-encrypted; an identity file is required")
        try:
            # The source repository may be a read-only remote mount. Keep
            # authenticated plaintext in the local temporary filesystem instead.
            staged = decrypt_artifact_stream_to_temp(
                stored, age_identity_file,
                tempfile.gettempdir(), age_executable=age_executable,
            )
        except ImageSecurityError as exc:
            raise PartitionRestoreError(f"image decryption/authentication failed: {exc}") from exc
        try:
            with open(staged, "rb") as plaintext:
                yield plaintext
        finally:
            try:
                os.unlink(staged)
            except FileNotFoundError:
                pass

def _decompress_to_temp(source: Any, compression: str, expected_raw_size: int | None, directory: str, executables: dict[str, str | None] | None = None):
    if compression == "none":
        decoder = source
    elif compression == "gzip":
        decoder = gzip.GzipFile(fileobj=source, mode="rb")
    elif compression == "xz":
        decoder = lzma.LZMAFile(source, mode="rb")
    elif compression in {"zstd", "lz4"}:
        try:
            decoder = ExternalDecompressionStream(source, compression, executables)
        except CompressionError as exc:
            raise PartitionRestoreError(str(exc)) from exc
    else:
        raise PartitionRestoreError("unsupported partition image compression")
    fd, staged_path = tempfile.mkstemp(prefix=".feclora-restore-", dir=directory)
    total = 0
    try:
        with os.fdopen(fd, "wb") as output:
            while True:
                chunk = decoder.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if expected_raw_size is not None and total > expected_raw_size:
                    raise PartitionRestoreError("decoded raw image exceeds partition size in manifest")
                output.write(chunk)
            if hasattr(decoder, "finish"):
                decoder.finish()
            if total <= 0:
                raise PartitionRestoreError("decoded partition image is empty")
            if expected_raw_size is not None and total != expected_raw_size:
                raise PartitionRestoreError("decoded raw image size does not match manifest")
            output.flush()
            os.fsync(output.fileno())
    except (OSError, EOFError, lzma.LZMAError, zlib.error, CompressionError) as exc:
        try:
            os.unlink(staged_path)
        except FileNotFoundError:
            pass
        raise PartitionRestoreError(f"partition image decompression failed: {exc}") from exc
    except Exception:
        try:
            os.unlink(staged_path)
        except FileNotFoundError:
            pass
        raise
    finally:
        if decoder is not source:
            decoder.close()
    source.seek(0)
    return staged_path, total

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

_FILESYSTEM_CHECKS = {
    "ext2": ("e2fsck", ["-f", "-n"]),
    "ext3": ("e2fsck", ["-f", "-n"]),
    "ext4": ("e2fsck", ["-f", "-n"]),
    "xfs": ("xfs_repair", ["-n"]),
    "btrfs": ("btrfs", ["check", "--readonly"]),
    "fat": ("fsck.fat", ["-n"]),
    "fat12": ("fsck.fat", ["-n"]),
    "fat16": ("fsck.fat", ["-n"]),
    "fat32": ("fsck.fat", ["-n"]),
    "vfat": ("fsck.fat", ["-n"]),
    "exfat": ("fsck.exfat", ["-n"]),
    "f2fs": ("fsck.f2fs", ["-n"]),
    "ntfs": ("ntfsfix", ["--no-action"]),
}


def _stop_process(process: Any) -> None:
    stop_process(process)


def _verify_raw_readback(
    dd: str,
    target: str,
    staged_path: str,
    expected_size: int,
    *,
    popen_factory: Callable[..., Any],
    effective_uid: Callable[[], int] | None,
) -> None:
    expected_digest = hashlib.sha256()
    with open(staged_path, "rb") as expected:
        while True:
            chunk = expected.read(1024 * 1024)
            if not chunk:
                break
            expected_digest.update(chunk)
    command = privileged_argv(
        [dd, f"if={target}", "bs=4M", "iflag=count_bytes",
         f"count={expected_size}", "status=none"],
        effective_uid=effective_uid,
    )
    stderr = tempfile.TemporaryFile(mode="w+b")
    process = None
    try:
        process = popen_factory(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=stderr, close_fds=True,
        )
        if process.stdout is None:
            raise PartitionRestoreError("read-back dd did not provide an output pipe")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = process.stdout.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        process.stdout.close()
        result = process.wait()
        if result != 0:
            stderr.seek(0)
            detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
            raise PartitionRestoreError("partition read-back dd failed" + (f": {detail}" if detail else ""))
        if total != expected_size or digest.digest() != expected_digest.digest():
            raise PartitionRestoreError("partition read-back verification failed: destination bytes differ from image")
    except (OSError, PrivilegeError) as exc:
        raise PartitionRestoreError(f"partition read-back verification could not run: {exc}") from exc
    finally:
        _stop_process(process)
        stderr.close()


def _verify_partclone_target(
    filesystem: str,
    target: str,
    available: dict[str, str | None],
    runner: Callable[..., Any],
    effective_uid: Callable[[], int] | None,
) -> None:
    specification = _FILESYSTEM_CHECKS.get(filesystem)
    if specification is None:
        raise PartitionRestoreError(f"no read-only post-restore checker is defined for {filesystem!r}")
    name, options = specification
    executable = available.get(name) or shutil.which(name)
    if not executable:
        raise PartitionRestoreError(f"{name} is required to verify the restored {filesystem} filesystem")
    try:
        command = privileged_argv([executable, *options, target], effective_uid=effective_uid)
        result = runner(
            command, check=False, capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
        raise PartitionRestoreError(f"post-restore filesystem check could not run: {exc}") from exc
    if getattr(result, "returncode", 0) != 0:
        detail = (getattr(result, "stderr", "") or "").strip()
        raise PartitionRestoreError(
            f"post-restore {filesystem} consistency check failed" + (f": {detail[:1000]}" if detail else "")
        )


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
    progress_callback: Callable[[int, int], None] | None = None,
    age_identity_file: str | os.PathLike[str] | None = None,
    minisign_public_key: str | os.PathLike[str] | None = None,
    require_signature: bool = False,
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
    signature_path = manifest_file + ".minisig"
    signature_present = os.path.lexists(signature_path)
    if require_signature and not signature_present:
        raise PartitionRestoreError("a minisign signature is required but this image has none")
    if signature_present and minisign_public_key is None:
        raise PartitionRestoreError("image is signed; a trusted minisign public key is required before restore")
    if minisign_public_key is not None:
        if not signature_present:
            raise PartitionRestoreError("minisign public key supplied but image signature is missing")
        try:
            verify_manifest_signature(manifest_file, minisign_public_key, signature_path=signature_path, minisign_executable=(executables or {}).get("minisign"))
        except ImageSecurityError as exc:
            raise PartitionRestoreError(f"manifest signature verification failed: {exc}") from exc
    elif require_signature:
        raise PartitionRestoreError("signature verification requires a trusted minisign public key")

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
        check_spec = _FILESYSTEM_CHECKS.get(artifact.filesystem or "")
        if check_spec is None:
            raise PartitionRestoreError(f"no read-only post-restore checker is defined for {artifact.filesystem!r}")
        check_name = check_spec[0]
        if not (available.get(check_name) or shutil.which(check_name)):
            raise PartitionRestoreError(f"{check_name} is required to verify the restored filesystem")
    else:
        executable = available.get("dd") or shutil.which("dd")
        if not executable:
            raise PartitionRestoreError("dd is required for raw partition restore")
    safety = target_safety_check or check_capture_source_safe
    try:
        safety(target_path)
    except SourceSafetyError as exc:
        raise PartitionRestoreError(f"unsafe restore target: {exc}") from exc

    with _verified_artifact_stream(repo, artifact, age_identity_file, available.get("age")) as image:
        staged_path, decoded_size = _decompress_to_temp(
            image, artifact.compression,
            manifest.source_size_bytes if artifact.format == "raw" else None,
            tempfile.gettempdir(), available,
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
            partclone_status_path = None
            if artifact.format == "partclone":
                argv = [executable, "-r", "-F", "-f", "1", "-s", staged_path, "-o", target_path]
                if _partclone_supports_json_status(executable):
                    partclone_status_path = staged_path + ".partclone-status.json"
                    argv.extend((
                        f"--json-status={partclone_status_path}", "--json-fresh=1",
                    ))
                stdin_mode = subprocess.DEVNULL
            else:
                argv = [executable, f"of={target_path}", "bs=4M", "conv=fsync", "status=none"]
                stdin_mode = subprocess.PIPE
            stderr = tempfile.TemporaryFile(mode="w+b")
            process = None
            try:
                if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
                    raise PartitionRestoreError("block-device identity changed before restore")
                factory = popen_factory or subprocess.Popen
                try:
                    command = privileged_argv(argv, effective_uid=effective_uid)
                    process = factory(
                        command, stdin=stdin_mode, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE if artifact.format == "partclone" else stderr, close_fds=True,
                    )
                except (OSError, PrivilegeError) as exc:
                    raise PartitionRestoreError(f"could not start restore utility: {exc}") from exc
                if artifact.format == "raw":
                    if process.stdin is None:
                        raise PartitionRestoreError("dd did not provide a writable input pipe")
                    written = 0
                    with open(staged_path, "rb") as raw_image:
                        while True:
                            chunk = raw_image.read(1024 * 1024)
                            if not chunk:
                                break
                            view = memoryview(chunk)
                            while view:
                                count = process.stdin.write(view)
                                if count is None or count <= 0:
                                    raise PartitionRestoreError("dd input pipe stopped accepting data")
                                written += count
                                view = view[count:]
                            if progress_callback is not None:
                                progress_callback(written, manifest.source_size_bytes)
                    process.stdin.close()
                    if written != manifest.source_size_bytes:
                        raise PartitionRestoreError("raw image byte count differs from manifest")
                if artifact.format == "partclone":
                    # Prefer Partclone's own block counters; retain the legacy
                    # stderr percentage parser for older packaged versions.
                    progress_stream = getattr(process, "stderr", None)
                    last_native_progress = None
                    if progress_stream is not None:
                        pending = bytearray()
                        while True:
                            char = progress_stream.read(1)
                            if not char:
                                break
                            stderr.write(char)
                            if char in (b"\r", b"\n"):
                                if partclone_status_path is not None:
                                    progress = _read_partclone_status(partclone_status_path)
                                else:
                                    line = bytes(pending)
                                    progress = _partclone_stderr_progress(line, manifest.source_size_bytes)
                                    if progress is None:
                                        match = re.search(rb"([0-9]+(?:\.[0-9]+)?)\s*%", line)
                                        if match:
                                            percent = max(0, min(100, int(float(match.group(1)))))
                                            progress = (
                                                manifest.source_size_bytes * percent // 100,
                                                manifest.source_size_bytes,
                                            )
                                if progress is not None and progress != last_native_progress:
                                    last_native_progress = progress
                                    if progress_callback is not None:
                                        progress_callback(*progress)
                                pending.clear()
                            else:
                                pending.extend(char)
                                if len(pending) > 4096:
                                    del pending[:-4096]
                        if pending and partclone_status_path is None:
                            progress = _partclone_stderr_progress(bytes(pending), manifest.source_size_bytes)
                            if progress is None:
                                match = re.search(rb"([0-9]+(?:\.[0-9]+)?)\s*%", bytes(pending))
                                if match:
                                    percent = max(0, min(100, int(float(match.group(1)))))
                                    progress = (
                                        manifest.source_size_bytes * percent // 100,
                                        manifest.source_size_bytes,
                                    )
                            if progress is not None and progress != last_native_progress and progress_callback is not None:
                                progress_callback(*progress)
                        if partclone_status_path is not None:
                            progress = _read_partclone_status(partclone_status_path)
                            if progress is not None and progress != last_native_progress and progress_callback is not None:
                                progress_callback(*progress)
                return_code = process.wait()
                if return_code != 0:
                    stderr.seek(0)
                    detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
                    raise PartitionRestoreError(
                        f"restore utility exited with status {return_code}" +
                        (f": {detail}" if detail else "")
                    )
                try:
                    safety(target_path)
                except SourceSafetyError as exc:
                    raise PartitionRestoreError(f"target became unsafe before read-back verification: {exc}") from exc
                if not validator(target_path):
                    raise PartitionRestoreError("target identity changed before verification")
                if initial_device_number is not None and os.stat(target_path).st_rdev != initial_device_number:
                    raise PartitionRestoreError("target block-device identity changed before verification")
                if artifact.format == "raw":
                    _verify_raw_readback(
                        executable, target_path, staged_path, manifest.source_size_bytes,
                        popen_factory=factory, effective_uid=effective_uid,
                    )
                else:
                    _verify_partclone_target(
                        artifact.filesystem or "", target_path, available, run, effective_uid,
                    )
                if progress_callback is not None and artifact.format == "partclone":
                    progress_callback(100, 100)
            finally:
                _stop_process(process)
                stderr.close()
        finally:
            if 'partclone_status_path' in locals() and partclone_status_path is not None:
                for status_file in (partclone_status_path, partclone_status_path + ".tmp"):
                    try:
                        os.unlink(status_file)
                    except FileNotFoundError:
                        pass
            try:
                os.unlink(staged_path)
            except FileNotFoundError:
                pass
    return manifest
