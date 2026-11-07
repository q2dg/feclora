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
import socket
import stat
import subprocess
import tempfile
from typing import Any, Callable

from feclora.storage.operation_log import DEFAULT_LOG_PATH, operation_record
from feclora.storage.disk_clone import DiskCloneError, _geometry
from feclora.storage.privilege import PrivilegeError, privileged_argv
from feclora.storage.source_safety import SourceSafetyError, check_capture_source_safe

from .tls import accept_mutual_tls, connect_mutual_tls
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
    send_terminal_result,
    send_verification_result,
    validate_endpoint_authorization,
    verify_peer_identity,
)

CHUNK_SIZE_BYTES = 1024 * 1024


class RemoteDiskCloneError(RuntimeError):
    """A remote disk clone was rejected or failed."""


class RemoteDiskCloneCancelled(RemoteDiskCloneError):
    """The operator cancelled a remote disk clone."""


def _shutdown_tls(tls_socket: Any) -> None:
    """Wake the peer immediately when a session fails instead of leaving it idle."""
    try:
        tls_socket.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        pass


def _resolve(executables: dict[str, str | None], name: str) -> str:
    path = executables.get(name) or shutil.which(name)
    if not path:
        raise RemoteDiskCloneError(f"{name} is required for remote disk cloning")
    return path


def _device_identity(
    path: str, validator: Callable[[str], bool], *, inspect_real_device: bool,
) -> int | None:
    try:
        if not validator(path):
            raise RemoteDiskCloneError(f"{path} is not an accessible block device")
        if not inspect_real_device:
            return None
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
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
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
            if cancel_check is not None and cancel_check():
                raise RemoteCloneCancelled("receiver operator cancelled destination read-back verification")
            chunk = process.stdout.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > expected_size:
                raise RemoteDiskCloneError("read-back returned more bytes than the source disk size")
            digest.update(chunk)
            if progress_callback is not None:
                progress_callback(total, expected_size)
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


def _send_remote_disk_impl(
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
    progress_callback: Callable[[int, int], None] | None = None,
) -> CloneVerificationResult:
    """Read and send a source disk; success requires receiver read-back acknowledgement."""
    available = executables or {}
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    safety = safety_check or check_capture_source_safe
    lsblk = _resolve(available, "lsblk")
    dd = _resolve(available, "dd")
    try:
        identity = _device_identity(header.source_device, validator, inspect_real_device=device_validator is None)
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
                progress_callback=progress_callback,
                send_terminal=False,
            )
            process.stdout.close()
            code = process.wait()
            if code != 0:
                raise RemoteDiskCloneError(f"source dd exited with status {code}")
            send_terminal_result(tls_socket, stream_result)
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
    except (DiskCloneError, RemoteCloneProtocolError, PrivilegeError, OSError, subprocess.SubprocessError) as exc:
        raise RemoteDiskCloneError(str(exc)) from exc


def _receive_remote_disk_impl(
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
    header: CloneSessionHeader | None = None,
) -> CloneVerificationResult:
    """Receive one disk, write it with dd, and verify the complete read-back."""
    available = executables or {}
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    safety = safety_check or check_capture_source_safe
    lsblk = _resolve(available, "lsblk")
    dd = _resolve(available, "dd")
    header = header or receive_session_header(tls_socket)
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
        identity = _device_identity(target, validator, inspect_real_device=device_validator is None)
        target_size, target_sector, read_only, _pttype = _geometry(target, lsblk, runner or subprocess.run)
        if read_only:
            raise RemoteDiskCloneError("receiver target disk is read-only")
        if target_size != header.source_size_bytes:
            raise RemoteDiskCloneError(
                "remote clone protocol v1 requires equal source and target disk capacities "
                "for exact whole-disk read-back verification"
            )
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
        stderr = tempfile.TemporaryFile(mode="w+b")
        process = factory(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=stderr, close_fds=True,
        )
        try:
            if process.stdin is None:
                raise RemoteDiskCloneError("receiver dd did not provide stdin")
            stream_result = receive_disk_stream(
                tls_socket, process.stdin, header.source_size_bytes,
                session_id=header.session_id, chunk_size=header.chunk_size_bytes,
                cancel_check=cancel_check,
                progress_callback=transfer_progress,
            )
            process.stdin.flush()
            process.stdin.close()
            code = process.wait()
            if code != 0:
                stderr.seek(0)
                detail = stderr.read(4096)
                raise RemoteDiskCloneError(
                    f"receiver dd exited with status {code}" +
                    (f": {detail.decode('utf-8', errors='replace').strip()}" if detail else "")
                )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
            stderr.close()
        _revalidate_device(target, identity, validator)
        _check_safe(target, safety)
        transfer_progress = (
            (lambda done, total: progress_callback(done, total * 2))
            if progress_callback is not None else None
        )
        readback_progress = (
            (lambda done, total: progress_callback(total + done, total * 2))
            if progress_callback is not None else None
        )
        # Transfer occupies the first half of the overall operation gauge;
        # the independent disk read-back occupies the second half.
        readback = _readback_digest(
            target, header.source_size_bytes, dd,
            popen_factory=factory, effective_uid=effective_uid,
            cancel_check=cancel_check, progress_callback=readback_progress,
        )
        if readback != stream_result.sha256:
            failure = CloneVerificationResult(
                session_id=header.session_id, status="failed",
                byte_count=header.source_size_bytes,
                stream_sha256=stream_result.sha256,
                readback_sha256=readback,
                error="receiver disk read-back SHA-256 differs from the received stream",
            )
            raise RemoteDiskCloneError(failure.error)
        result = CloneVerificationResult(
            session_id=header.session_id, status="verified",
            byte_count=header.source_size_bytes,
            stream_sha256=stream_result.sha256,
            readback_sha256=readback,
        )
        if progress_callback is not None:
            progress_callback(header.source_size_bytes * 2, header.source_size_bytes * 2)
        return result
    except RemoteCloneCancelled as exc:
        raise RemoteDiskCloneCancelled(str(exc)) from exc
    except (DiskCloneError, RemoteCloneProtocolError, PrivilegeError, OSError, subprocess.SubprocessError) as exc:
        raise RemoteDiskCloneError(str(exc)) from exc


def send_remote_disk(
    tls_socket: Any,
    header: CloneSessionHeader,
    *,
    operation_log_path: str = str(DEFAULT_LOG_PATH),
    **kwargs: Any,
) -> CloneVerificationResult:
    """Journal a source operation and send only after peer identity is checked."""
    expected_peer_identity = kwargs.get("expected_peer_identity")
    if not isinstance(expected_peer_identity, str):
        raise RemoteDiskCloneError("expected receiver identity is required")
    verify_peer_identity(tls_socket, expected_peer_identity)
    target = f"{header.source_device} -> {header.receiver_identity}:{header.receiver_target_device}"
    try:
        with operation_record(
            "remote-disk-send", target, image_id=header.session_id,
            log_path=operation_log_path,
        ):
            return _send_remote_disk_impl(tls_socket, header, **kwargs)
    except BaseException:
        _shutdown_tls(tls_socket)
        raise


def receive_remote_disk(
    tls_socket: Any,
    *,
    operation_log_path: str = str(DEFAULT_LOG_PATH),
    **kwargs: Any,
) -> CloneVerificationResult:
    """Journal the receiver operation before writing and acknowledge after durable completion."""
    expected_peer_identity = kwargs.get("expected_peer_identity")
    if not isinstance(expected_peer_identity, str):
        raise RemoteDiskCloneError("expected source identity is required")
    try:
        verify_peer_identity(tls_socket, expected_peer_identity)
        header = receive_session_header(tls_socket)
        target = header.receiver_target_device
        with operation_record(
            "remote-disk-receive", target, image_id=header.session_id,
            log_path=operation_log_path,
        ):
            result = _receive_remote_disk_impl(
                tls_socket, header=header, **kwargs,
            )
        # The receiver journal's completed event is durable before the sender
        # is told that the destructive operation succeeded.
        send_verification_result(tls_socket, result)
        return result
    except BaseException:
        _shutdown_tls(tls_socket)
        raise


def serve_remote_clone_once(
    listener: Any,
    tls_context: Any,
    header: CloneSessionHeader,
    *,
    local_identity: str,
    expected_peer_identity: str,
    confirmation: str,
    **kwargs: Any,
) -> CloneVerificationResult:
    """Accept exactly one receiver connection and serve one source-disk session."""
    accepted, _address = listener.accept()
    tls_socket = accept_mutual_tls(
        tls_context, accepted, expected_peer_identity=expected_peer_identity,
    )
    with tls_socket:
        return send_remote_disk(
            tls_socket, header,
            local_identity=local_identity,
            expected_peer_identity=expected_peer_identity,
            confirmation=confirmation,
            **kwargs,
        )


def connect_remote_clone(
    host: str,
    port: int,
    tls_context: Any,
    *,
    local_identity: str,
    expected_peer_identity: str,
    confirmation: str,
    **kwargs: Any,
) -> CloneVerificationResult:
    """Connect as the receiver, complete mTLS, and run one destructive clone session."""
    tls_socket = connect_mutual_tls(
        tls_context, host, port,
        expected_peer_identity=expected_peer_identity,
    )
    with tls_socket:
        return receive_remote_disk(
            tls_socket,
            local_identity=local_identity,
            expected_peer_identity=expected_peer_identity,
            confirmation=confirmation,
            **kwargs,
        )
