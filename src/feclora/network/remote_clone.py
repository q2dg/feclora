"""One-to-one remote whole-disk cloning over a pre-established mutual-TLS socket.

The caller is responsible for creating the TLS socket with
create_mutual_tls_context(), completing the handshake, and supplying the
expected identities. This module owns local device validation, explicit
per-endpoint authorization, bounded dd streaming, and receiver read-back.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from feclora.storage.disk_clone import _geometry
from feclora.storage.privilege import PrivilegeError, privileged_argv
from feclora.storage.source_safety import SourceSafetyError, check_capture_source_safe

from .remote_clone_protocol import (
    CloneSessionHeader,
    CloneVerificationResult,
    RemoteCloneCancelled,
    RemoteCloneProtocolError,
    authorize_endpoint,
    receive_disk_stream,
    receive_session_header,
    receive_verification_result,
    send_disk_stream,
    send_session_header,
    send_verification_result,
    validate_endpoint_authorization,
    verify_peer_identity,
)

CHUNK_SIZE_BYTES = 1024 * 1024


class RemoteDiskCloneError(RuntimeError):
    """A remote disk clone was rejected or failed."""


class RemoteDiskCloneCancelled(RemoteDiskCloneError):
    """The operator cancelled a remote disk clone."""


def _resolve(executables: dict[str, str | None], name: str) -> str:
    path = executables.get(name) or shutil.which(name)
    if not path:
        raise RemoteDiskCloneError(f"{name} is required for remote disk cloning")
    return path


def _device_identity(path: str, validator: Callable[[str], bool]) -> int | None:
    try:
        if not validator(path):
            raise RemoteDiskCloneError(f"{path} is not an accessible block device")
        info = os.stat(path)
        return info.st_rdev if stat.S_ISBLK(info.st_mode) else None
    except OSError as exc:
        raise RemoteDiskCloneError(f"cannot inspect block device {path}: {exc}") from exc


def _revalidate_device(path: str, identity: int | None, validator: Callable[[str], bool]) -> None:
    if not validator(path):
        raise RemoteDiskCloneError(f"block device {path} is no longer available")
    if identity is not None:
        try:
            if not stat.S_ISBLK(os.stat(path).st_mode) or os.stat(path).st_rdev != identity:
                raise RemoteDiskCloneError(f"block-device identity changed for {path}")
        except OSError as exc:
            raise RemoteDiskCloneError(f"cannot revalidate block device {path}: {exc}") from exc


def _check_safe(path: str, safety_check: Callable[[str], None]) -> None:
    try:
        safety_check(path)
    except (SourceSafetyError, OSError, RuntimeError) as exc:
        raise RemoteDiskCloneError(f"unsafe remote clone device {path}: {exc}") from exc


def _readback_digest(
    target: str,
    expected_size: int,
    dd: str,
    *,
    popen_factory: Callable[..., Any],
    effective_uid: Callable[[], int] | None,
) -> str:
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
            raise RemoteDiskCloneError("read-back dd did not provide stdout")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = process.stdout.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > expected_size:
                raise RemoteDiskCloneError("read-back returned more bytes than the source disk size")
            digest.update(chunk)
        process.stdout.close()
        code = process.wait()
        if code != 0:
            stderr.seek(0)
            detail = stderr.read(4096).decode("utf-8", errors="replace").strip()
            raise RemoteDiskCloneError("destination read-back failed" + (f": {detail}" if detail else ""))
        if total != expected_size:
            raise RemoteDiskCloneError(
                f"destination read-back was short ({total} of {expected_size} bytes)"
            )
        return digest.hexdigest()
    except (OSError, PrivilegeError) as exc:
        raise RemoteDiskCloneError(f"could not verify destination disk: {exc}") from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        stderr.close()


def send_remote_disk(
    tls_socket: Any,
    header: CloneSessionHeader,
    *,
    local_identity: str,
    expected_peer_identity: str,
    confirmation: str,
    executables: dict[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    runner: Callable[..., Any] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> CloneVerificationResult:
    """Read and send a source disk; success requires receiver read-back acknowledgement."""
    available = executables or {}
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    safety = safety_check or check_capture_source_safe
    lsblk = _resolve(available, "lsblk")
    dd = _resolve(available, "dd")
    try:
        identity = _device_identity(header.source_device, validator)
        size, sector, read_only, _pttype = _geometry(header.source_device, lsblk, runner or subprocess.run)
        if size != header.source_size_bytes or sector != header.logical_sector_size:
            raise RemoteDiskCloneError("source disk geometry differs from the approved session header")
        # A read-only source is valid; it is never opened for writing.
        _check_safe(header.source_device, safety)
        verify_peer_identity(tls_socket, expected_peer_identity)
        approval = authorize_endpoint(
            header, role="source", local_identity=local_identity,
            expected_peer_identity=expected_peer_identity, confirmation=confirmation,
        )
        validate_endpoint_authorization(
            approval, header, role="source", device_path=header.source_device,
        )
        _revalidate_device(header.source_device, identity, validator)
        _check_safe(header.source_device, safety)
        send_session_header(tls_socket, header)
        command = privileged_argv(
            [dd, f"if={header.source_device}", "bs=4M", "iflag=count_bytes",
             f"count={header.source_size_bytes}", "status=none"],
            effective_uid=effective_uid,
        )
        factory = popen_factory or subprocess.Popen
        process = factory(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        try:
            if process.stdout is None:
                raise RemoteDiskCloneError("source dd did not provide stdout")
            stream_result = send_disk_stream(
                tls_socket, process.stdout, header.source_size_bytes,
                session_id=header.session_id, chunk_size=header.chunk_size_bytes,
                cancel_check=cancel_check,
            )
            process.stdout.close()
            code = process.wait()
            if code != 0:
                raise RemoteDiskCloneError(f"source dd exited with status {code}")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
        return receive_verification_result(
            tls_socket, session_id=header.session_id,
            expected_bytes=header.source_size_bytes,
            expected_stream_sha256=stream_result.sha256,
        )
    except RemoteCloneCancelled as exc:
        raise RemoteDiskCloneCancelled(str(exc)) from exc
    except (RemoteCloneProtocolError, PrivilegeError, OSError, subprocess.SubprocessError) as exc:
        raise RemoteDiskCloneError(str(exc)) from exc


def receive_remote_disk(
    tls_socket: Any,
    *,
    local_identity: str,
    expected_peer_identity: str,
    confirmation: str,
    executables: dict[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    runner: Callable[..., Any] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CloneVerificationResult:
    """Receive one disk, write it with dd, read it back, and acknowledge only verified data."""
    available = executables or {}
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    safety = safety_check or check_capture_source_safe
    lsblk = _resolve(available, "lsblk")
    dd = _resolve(available, "dd")
    header = receive_session_header(tls_socket)
    try:
        verify_peer_identity(tls_socket, expected_peer_identity)
        approval = authorize_endpoint(
            header, role="receiver", local_identity=local_identity,
            expected_peer_identity=expected_peer_identity, confirmation=confirmation,
        )
        validate_endpoint_authorization(
            approval, header, role="receiver", device_path=header.receiver_target_device,
        )
        target = header.receiver_target_device
        identity = _device_identity(target, validator)
        target_size, target_sector, read_only, _pttype = _geometry(target, lsblk, runner or subprocess.run)
        if read_only:
            raise RemoteDiskCloneError("receiver target disk is read-only")
        if target_size < header.source_size_bytes:
            raise RemoteDiskCloneError("receiver target disk is smaller than the source disk")
        if target_sector != header.logical_sector_size:
            raise RemoteDiskCloneError("receiver target logical sector size differs from source")
        _check_safe(target, safety)
        _revalidate_device(target, identity, validator)
        _check_safe(target, safety)
        command = privileged_argv(
            [dd, f"of={target}", "bs=4M", "conv=fsync", "status=none"],
            effective_uid=effective_uid,
        )
        factory = popen_factory or subprocess.Popen
        process = factory(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, close_fds=True,
        )
        try:
            if process.stdin is None:
                raise RemoteDiskCloneError("receiver dd did not provide stdin")
            stream_result = receive_disk_stream(
                tls_socket, process.stdin, header.source_size_bytes,
                session_id=header.session_id, chunk_size=header.chunk_size_bytes,
                cancel_check=cancel_check,
            )
            process.stdin.flush()
            process.stdin.close()
            code = process.wait()
            if code != 0:
                detail = b""
                if process.stderr is not None:
                    detail = process.stderr.read(4096)
                raise RemoteDiskCloneError(
                    f"receiver dd exited with status {code}" +
                    (f": {detail.decode('utf-8', errors='replace').strip()}" if detail else "")
                )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
        _revalidate_device(target, identity, validator)
        _check_safe(target, safety)
        readback = _readback_digest(
            target, header.source_size_bytes, dd,
            popen_factory=factory, effective_uid=effective_uid,
        )
        if readback != stream_result.sha256:
            raise RemoteDiskCloneError("receiver disk read-back SHA-256 differs from the received stream")
        result = CloneVerificationResult(
            session_id=header.session_id, status="verified",
            byte_count=header.source_size_bytes,
            stream_sha256=stream_result.sha256,
            readback_sha256=readback,
        )
        send_verification_result(tls_socket, result)
        if progress_callback is not None:
            progress_callback(header.source_size_bytes, header.source_size_bytes)
        return result
    except RemoteCloneCancelled as exc:
        raise RemoteDiskCloneCancelled(str(exc)) from exc
    except (RemoteCloneProtocolError, PrivilegeError, OSError, subprocess.SubprocessError) as exc:
        raise RemoteDiskCloneError(str(exc)) from exc
