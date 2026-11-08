"""Authenticated, signed image-set transfer over an established TLS socket.

The TLS session and peer identity must already be authenticated by the control
protocol. This module transfers a manifest and its artifacts; it never writes
to block devices. The receiver publishes a complete image set atomically only
after signature, size and SHA-256 checks succeed.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import struct
import tempfile
from pathlib import Path
from typing import Any

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.image_security import ImageSecurityError, verify_manifest_signature

_MAGIC = b"FECLORA-IMAGESET\x01"
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_SIGNATURE_BYTES = 16 * 1024
_MAX_ARTIFACTS = 64
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


class ImageTransferError(RuntimeError):
    """A signed image set could not be safely transferred or published."""


def _recv_exact(sock: Any, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ImageTransferError("peer closed the image transfer before the expected byte count")
        data.extend(chunk)
    return bytes(data)


def _read_length(sock: Any, maximum: int, label: str) -> int:
    value = struct.unpack("!I", _recv_exact(sock, 4))[0]
    if value <= 0 or value > maximum:
        raise ImageTransferError(f"{label} length is outside the permitted range")
    return value


def _open_regular(path: str) -> tuple[int, os.stat_result]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise ImageTransferError("image-set member must be a regular file")
        return fd, info
    except OSError as exc:
        raise ImageTransferError(f"cannot safely open image-set member: {exc}") from exc


def _hash_fd(fd: int, expected_size: int, label: str) -> str:
    digest = hashlib.sha256()
    total = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, _CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > expected_size:
            raise ImageTransferError(f"{label} is larger than its manifest size")
        digest.update(chunk)
    if total != expected_size:
        raise ImageTransferError(f"{label} size differs from its manifest")
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def send_image_set(
    tls_socket: Any,
    repository: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    *,
    expected_image_id: str,
    trusted_public_key: str | os.PathLike[str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> ImageManifest:
    """Verify and send one complete signed image set to an authenticated peer."""
    repo = os.path.abspath(os.fspath(repository))
    if not stat.S_ISDIR(os.lstat(repo).st_mode):
        raise ImageTransferError("image repository must be a real directory")
    manifest_file = os.fspath(manifest_path)
    if not os.path.isabs(manifest_file):
        manifest_file = os.path.join(repo, manifest_file)
    manifest_fd, manifest_info = _open_regular(manifest_file)
    signature_fd = None
    artifact_fds: list[tuple[Any, int]] = []
    try:
        if manifest_info.st_size > _MAX_MANIFEST_BYTES:
            raise ImageTransferError("manifest exceeds the 1 MiB transfer limit")
        manifest_bytes = os.read(manifest_fd, _MAX_MANIFEST_BYTES + 1)
        if len(manifest_bytes) != manifest_info.st_size:
            raise ImageTransferError("manifest changed while being read")
        try:
            manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
        except (UnicodeError, ManifestValidationError) as exc:
            raise ImageTransferError(f"invalid image manifest: {exc}") from exc
        if manifest.image_id != expected_image_id:
            raise ImageTransferError("source image identifier does not match the armed deployment job")
        if len(manifest.artifacts) > _MAX_ARTIFACTS:
            raise ImageTransferError("image set contains too many artifacts")
        reserved_names = {manifest.image_id + ".manifest.json", manifest.image_id + ".manifest.json.minisig"}
        if any(item.filename in reserved_names for item in manifest.artifacts):
            raise ImageTransferError("artifact filename collides with the manifest commit marker")
        signature_path = manifest_file + ".minisig"
        signature_fd, signature_info = _open_regular(signature_path)
        if not 1 <= signature_info.st_size <= _MAX_SIGNATURE_BYTES:
            raise ImageTransferError("manifest signature size is outside the permitted range")
        signature = os.read(signature_fd, _MAX_SIGNATURE_BYTES + 1)
        if len(signature) != signature_info.st_size:
            raise ImageTransferError("manifest signature changed while being read")
        with tempfile.TemporaryDirectory(prefix="feclora-send-manifest-") as verify_dir:
            os.chmod(verify_dir, 0o700)
            verify_manifest = os.path.join(verify_dir, "manifest.json")
            verify_signature = verify_manifest + ".minisig"
            for verify_path, payload in ((verify_manifest, manifest_bytes), (verify_signature, signature)):
                fd = os.open(verify_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            try:
                verify_manifest_signature(
                    verify_manifest, trusted_public_key, signature_path=verify_signature,
                )
            except (ImageSecurityError, OSError) as exc:
                raise ImageTransferError(f"source manifest signature is invalid: {exc}") from exc

        total_bytes = 0
        for artifact in manifest.artifacts:
            if artifact.size_bytes > _MAX_ARTIFACT_BYTES:
                raise ImageTransferError("artifact exceeds the 16 TiB transfer limit")
            total_bytes += artifact.size_bytes
            if total_bytes > _MAX_ARTIFACT_BYTES:
                raise ImageTransferError("image set exceeds the 16 TiB total transfer limit")
            path = os.path.join(repo, artifact.filename)
            fd, info = _open_regular(path)
            if info.st_size != artifact.size_bytes:
                os.close(fd)
                raise ImageTransferError(f"artifact size differs from manifest: {artifact.filename}")
            digest = _hash_fd(fd, artifact.size_bytes, artifact.filename)
            if digest != artifact.sha256:
                os.close(fd)
                raise ImageTransferError(f"artifact SHA-256 differs from manifest: {artifact.filename}")
            artifact_fds.append((artifact, fd))

        tls_socket.sendall(_MAGIC + struct.pack("!I", len(manifest_bytes)) + manifest_bytes
                           + struct.pack("!I", len(signature)) + signature)
        if progress_callback is not None:
            progress_callback(0, total_bytes)
        transferred = 0
        for artifact, fd in artifact_fds:
            remaining = artifact.size_bytes
            while remaining:
                chunk = os.read(fd, min(_CHUNK_BYTES, remaining))
                if not chunk:
                    raise ImageTransferError(f"artifact truncated during transfer: {artifact.filename}")
                tls_socket.sendall(chunk)
                remaining -= len(chunk)
                transferred += len(chunk)
                if progress_callback is not None:
                    progress_callback(transferred, total_bytes)
        return manifest
    except OSError as exc:
        raise ImageTransferError(f"image-set transfer failed: {exc}") from exc
    finally:
        os.close(manifest_fd)
        if signature_fd is not None:
            os.close(signature_fd)
        for _artifact, fd in artifact_fds:
            os.close(fd)


def receive_image_set(
    tls_socket: Any,
    repository: str | os.PathLike[str],
    *,
    expected_image_id: str,
    trusted_public_key: str | os.PathLike[str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """Receive, verify and atomically publish an image set; returns manifest path."""
    repo = os.path.abspath(os.fspath(repository))
    try:
        repo_info = os.lstat(repo)
    except OSError as exc:
        raise ImageTransferError("destination image repository is unavailable") from exc
    if not stat.S_ISDIR(repo_info.st_mode):
        raise ImageTransferError("destination image repository must be a real directory")
    if not isinstance(expected_image_id, str) or not expected_image_id:
        raise ImageTransferError("expected image identifier is required")
    stage = tempfile.mkdtemp(prefix=".feclora-transfer-", dir=repo)
    os.chmod(stage, 0o700)
    published: list[str] = []
    try:
        magic = _recv_exact(tls_socket, len(_MAGIC))
        if magic != _MAGIC:
            raise ImageTransferError("peer did not send a Feclora image-set header")
        manifest_length = _read_length(tls_socket, _MAX_MANIFEST_BYTES, "manifest")
        manifest_bytes = _recv_exact(tls_socket, manifest_length)
        signature_length = _read_length(tls_socket, _MAX_SIGNATURE_BYTES, "signature")
        signature = _recv_exact(tls_socket, signature_length)
        try:
            manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
        except (UnicodeError, ManifestValidationError) as exc:
            raise ImageTransferError(f"received manifest is invalid: {exc}") from exc
        if manifest.image_id != expected_image_id:
            raise ImageTransferError("received image identifier does not match the armed deployment job")
        if len(manifest.artifacts) > _MAX_ARTIFACTS:
            raise ImageTransferError("image set contains too many artifacts")
        reserved_names = {manifest.image_id + ".manifest.json", manifest.image_id + ".manifest.json.minisig"}
        if any(item.filename in reserved_names for item in manifest.artifacts):
            raise ImageTransferError("artifact filename collides with the manifest commit marker")
        manifest_stage = os.path.join(stage, expected_image_id + ".manifest.json")
        signature_stage = manifest_stage + ".minisig"
        for path, payload in ((manifest_stage, manifest_bytes), (signature_stage, signature)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            verify_manifest_signature(
                manifest_stage, trusted_public_key, signature_path=signature_stage,
            )
        except (ImageSecurityError, OSError) as exc:
            raise ImageTransferError(f"received manifest signature is invalid: {exc}") from exc

        total_bytes = 0
        staged_artifacts: list[tuple[str, str]] = []
        for artifact in manifest.artifacts:
            if artifact.size_bytes > _MAX_ARTIFACT_BYTES:
                raise ImageTransferError("artifact exceeds the 16 TiB transfer limit")
            total_bytes += artifact.size_bytes
            if total_bytes > _MAX_ARTIFACT_BYTES:
                raise ImageTransferError("image set exceeds the 16 TiB total transfer limit")
        try:
            free_bytes = shutil.disk_usage(repo).free
        except OSError as exc:
            raise ImageTransferError(f"cannot check image staging free space: {exc}") from exc
        required_bytes = total_bytes + manifest_length + signature_length
        if free_bytes < required_bytes:
            raise ImageTransferError(
                f"insufficient staging space: need {required_bytes} bytes, have {free_bytes}"
            )
        if progress_callback is not None:
            progress_callback(0, total_bytes)
        transferred = 0
        for artifact in manifest.artifacts:
            path = os.path.join(stage, artifact.filename)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            digest = hashlib.sha256()
            remaining = artifact.size_bytes
            try:
                with os.fdopen(fd, "wb") as stream:
                    while remaining:
                        chunk = _recv_exact(tls_socket, min(_CHUNK_BYTES, remaining))
                        stream.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                        transferred += len(chunk)
                        if progress_callback is not None:
                            progress_callback(transferred, total_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                raise
            if digest.hexdigest() != artifact.sha256:
                raise ImageTransferError(f"received artifact SHA-256 mismatch: {artifact.filename}")
            staged_artifacts.append((path, os.path.join(repo, artifact.filename)))

        # Publish payload files first; manifest and signature are the commit marker.
        for source, destination in staged_artifacts:
            os.link(source, destination, follow_symlinks=False)
            published.append(destination)
        final_manifest = os.path.join(repo, expected_image_id + ".manifest.json")
        final_signature = final_manifest + ".minisig"
        os.link(manifest_stage, final_manifest, follow_symlinks=False)
        published.append(final_manifest)
        os.link(signature_stage, final_signature, follow_symlinks=False)
        published.append(final_signature)
        directory_fd = os.open(repo, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return final_manifest
    except (OSError, ImageTransferError) as exc:
        for path in reversed(published):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        if isinstance(exc, ImageTransferError):
            raise
        raise ImageTransferError(f"could not publish received image set: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
