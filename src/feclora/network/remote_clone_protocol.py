"""Bounded framing and integrity primitives for one-to-one remote disk cloning.

TLS setup and local device authorization are deliberately separate concerns.
Callers must use TLS that authenticates the Server certificate only. Client
identity is not authenticated; explicit local authorization at both endpoints
and validated streams/devices remain required.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import posixpath
import re
import socket
import ssl
import struct
import uuid
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable

PROTOCOL_VERSION = 1
MAX_HEADER_BYTES = 16 * 1024
MAX_TERMINAL_BYTES = 1024
MIN_CHUNK_BYTES = 64 * 1024
MAX_CHUNK_BYTES = 4 * 1024 * 1024
DEFAULT_CHUNK_BYTES = 1024 * 1024
_MAX_DEVICE_BYTES = (1 << 63) - 1
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RemoteCloneProtocolError(RuntimeError):
    """A remote clone frame or stream is invalid."""


class RemoteCloneCancelled(RemoteCloneProtocolError):
    """The operator cancelled the remote clone transfer."""


def _positive_integer(value: Any, field: str, maximum: int = _MAX_DEVICE_BYTES) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise RemoteCloneProtocolError(f"{field} must be an integer between 1 and {maximum}")
    return value


def _bounded_string(value: Any, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise RemoteCloneProtocolError(f"{field} must be a non-empty string of at most {maximum} characters")
    if any(ord(char) < 32 for char in value):
        raise RemoteCloneProtocolError(f"{field} contains control characters")
    return value


def _validate_chunk_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_CHUNK_BYTES <= value <= MAX_CHUNK_BYTES:
        raise RemoteCloneProtocolError(
            f"chunk_size_bytes must be between {MIN_CHUNK_BYTES} and {MAX_CHUNK_BYTES}"
        )
    return value


@dataclass(frozen=True)
class CloneSessionHeader:
    session_id: str
    source_device: str
    receiver_target_device: str
    source_size_bytes: int
    logical_sector_size: int
    chunk_size_bytes: int = DEFAULT_CHUNK_BYTES
    schema_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.session_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RemoteCloneProtocolError("session_id must be a UUID") from exc
        if str(parsed) != self.session_id:
            raise RemoteCloneProtocolError("session_id must use canonical UUID notation")
        if (not isinstance(self.source_device, str) or not self.source_device.startswith("/dev/")
                or len(self.source_device) > 256 or any(ord(c) < 32 for c in self.source_device)
                or posixpath.normpath(self.source_device) != self.source_device
                or "//" in self.source_device):
            raise RemoteCloneProtocolError("source_device must be a normalized /dev path")
        if (not isinstance(self.receiver_target_device, str) or not self.receiver_target_device.startswith("/dev/")
                or len(self.receiver_target_device) > 256 or any(ord(c) < 32 for c in self.receiver_target_device)
                or posixpath.normpath(self.receiver_target_device) != self.receiver_target_device
                or "//" in self.receiver_target_device):
            raise RemoteCloneProtocolError("receiver_target_device must be a normalized /dev path")
        _positive_integer(self.source_size_bytes, "source_size_bytes")
        if (isinstance(self.logical_sector_size, bool) or not isinstance(self.logical_sector_size, int)
                or self.logical_sector_size not in {512, 4096}):
            raise RemoteCloneProtocolError("logical_sector_size must be 512 or 4096")
        _validate_chunk_size(self.chunk_size_bytes)
        if (isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int)
                or self.schema_version != PROTOCOL_VERSION):
            raise RemoteCloneProtocolError("unsupported remote clone protocol version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "source_device": self.source_device,
            "receiver_target_device": self.receiver_target_device,
            "source_size_bytes": self.source_size_bytes,
            "logical_sector_size": self.logical_sector_size,
            "chunk_size_bytes": self.chunk_size_bytes,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CloneSessionHeader":
        if not isinstance(value, dict):
            raise RemoteCloneProtocolError("session header must be a JSON object")
        required = {
            "schema_version", "session_id",
            "source_device", "receiver_target_device", "source_size_bytes", "logical_sector_size", "chunk_size_bytes",
        }
        if set(value) != required:
            raise RemoteCloneProtocolError("session header has missing or unknown fields")
        try:
            return cls(**value)
        except TypeError as exc:
            raise RemoteCloneProtocolError(f"invalid session header fields: {exc}") from exc

 
@dataclass(frozen=True)
class CloneEndpointAuthorization:
    session_id: str
    role: str
    device_path: str


def authorize_endpoint(
    header: CloneSessionHeader,
    *,
    role: str,
    confirmation: str,
) -> CloneEndpointAuthorization:
    """Validate an explicit, role-specific local approval for this exact session."""
    if role == "source":
        device_path = header.source_device
        required_phrase = f"READ {device_path}"
    elif role == "receiver":
        device_path = header.receiver_target_device
        required_phrase = f"ERASE {device_path}"
    else:
        raise RemoteCloneProtocolError("endpoint role must be 'source' or 'receiver'")
    if confirmation != required_phrase:
        raise RemoteCloneProtocolError(f"explicit {role} authorization required: {required_phrase}")
    return CloneEndpointAuthorization(
        session_id=header.session_id,
        role=role,
        device_path=device_path,
    )


def validate_endpoint_authorization(
    authorization: CloneEndpointAuthorization,
    header: CloneSessionHeader,
    *,
    role: str,
    device_path: str,
) -> None:
    """Recheck the session-bound approval immediately before a device operation."""
    if (authorization.session_id != header.session_id or authorization.role != role
            or authorization.device_path != device_path):
        raise RemoteCloneProtocolError("endpoint authorization does not cover this session, role and device")


@dataclass(frozen=True)
class CloneSessionReady:
    session_id: str
    target_device: str
    status: str = "ready"

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.session_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RemoteCloneProtocolError("ready session_id must be a UUID") from exc
        if str(parsed) != self.session_id:
            raise RemoteCloneProtocolError("ready session_id must use canonical UUID notation")
        if (not isinstance(self.target_device, str) or not self.target_device.startswith("/dev/")
                or len(self.target_device) > 256 or any(ord(c) < 32 for c in self.target_device)
                or posixpath.normpath(self.target_device) != self.target_device
                or "//" in self.target_device):
            raise RemoteCloneProtocolError("ready target_device must be a normalized /dev path")
        if self.status != "ready":
            raise RemoteCloneProtocolError("session ready status must be 'ready'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_device": self.target_device,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CloneSessionReady":
        required = {"session_id", "target_device", "status"}
        if not isinstance(value, dict) or set(value) != required:
            raise RemoteCloneProtocolError("session ready frame has missing or unknown fields")
        return cls(**value)


def send_session_ready(sock: Any, ready: CloneSessionReady) -> None:
    payload = json.dumps(ready.to_dict(), sort_keys=True, separators=(",", ":")).encode("ascii")
    _send_frame(sock, payload, MAX_TERMINAL_BYTES)


def receive_session_ready(
    sock: Any,
    *,
    session_id: str,
    expected_target_device: str,
) -> CloneSessionReady:
    payload = _recv_frame(sock, MAX_TERMINAL_BYTES)
    try:
        value = json.loads(payload.decode("ascii"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteCloneProtocolError(f"invalid session ready JSON: {exc}") from exc
    ready = CloneSessionReady.from_dict(value)
    if ready.session_id != session_id or ready.target_device != expected_target_device:
        raise RemoteCloneProtocolError("receiver readiness is bound to a different session or target device")
    return ready


@dataclass(frozen=True)
class CloneStreamResult:
    session_id: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.session_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RemoteCloneProtocolError("terminal session_id must be a UUID") from exc
        if str(parsed) != self.session_id:
            raise RemoteCloneProtocolError("terminal session_id must use canonical UUID notation")
        _positive_integer(self.byte_count, "byte_count")
        if not isinstance(self.sha256, str) or not _HEX_SHA256.fullmatch(self.sha256):
            raise RemoteCloneProtocolError("sha256 must be a lowercase 64-character hexadecimal digest")

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "byte_count": self.byte_count, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: Any) -> "CloneStreamResult":
        if not isinstance(value, dict) or set(value) != {"session_id", "byte_count", "sha256"}:
            raise RemoteCloneProtocolError("terminal result has missing or unknown fields")
        return cls(**value)


@dataclass(frozen=True)
class CloneVerificationResult:
    session_id: str
    status: str
    byte_count: int
    stream_sha256: str
    readback_sha256: str | None
    error: str | None = None

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.session_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RemoteCloneProtocolError("verification session_id must be a UUID") from exc
        if str(parsed) != self.session_id:
            raise RemoteCloneProtocolError("verification session_id must use canonical UUID notation")
        if not isinstance(self.status, str) or self.status not in {"verified", "failed"}:
            raise RemoteCloneProtocolError("verification status must be verified or failed")
        _positive_integer(self.byte_count, "byte_count")
        if not isinstance(self.stream_sha256, str) or not _HEX_SHA256.fullmatch(self.stream_sha256):
            raise RemoteCloneProtocolError("stream_sha256 must be a lowercase SHA-256 digest")
        if self.readback_sha256 is not None and (
            not isinstance(self.readback_sha256, str) or not _HEX_SHA256.fullmatch(self.readback_sha256)
        ):
            raise RemoteCloneProtocolError("readback_sha256 must be a lowercase SHA-256 digest or null")
        if self.status == "verified":
            if self.readback_sha256 is None or not hmac.compare_digest(self.stream_sha256, self.readback_sha256):
                raise RemoteCloneProtocolError("verified result requires matching stream and read-back digests")
            if self.error is not None:
                raise RemoteCloneProtocolError("verified result cannot contain an error")
        elif not isinstance(self.error, str) or not self.error or len(self.error) > 512:
            raise RemoteCloneProtocolError("failed result requires a bounded error description")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "byte_count": self.byte_count,
            "stream_sha256": self.stream_sha256,
            "readback_sha256": self.readback_sha256,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CloneVerificationResult":
        required = {"session_id", "status", "byte_count", "stream_sha256", "readback_sha256", "error"}
        if not isinstance(value, dict) or set(value) != required:
            raise RemoteCloneProtocolError("verification result has missing or unknown fields")
        return cls(**value)


def send_verification_result(sock: Any, result: CloneVerificationResult) -> None:
    payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")).encode("ascii")
    _send_frame(sock, payload, MAX_TERMINAL_BYTES)


def receive_verification_result(
    sock: Any,
    *,
    session_id: str,
    expected_bytes: int,
    expected_stream_sha256: str,
) -> CloneVerificationResult:
    payload = _recv_frame(sock, MAX_TERMINAL_BYTES)
    try:
        value = json.loads(payload.decode("ascii"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteCloneProtocolError(f"invalid receiver verification JSON: {exc}") from exc
    result = CloneVerificationResult.from_dict(value)
    if result.session_id != session_id or result.byte_count != expected_bytes:
        raise RemoteCloneProtocolError("receiver verification result is bound to a different session or byte count")
    if not hmac.compare_digest(result.stream_sha256, expected_stream_sha256):
        raise RemoteCloneProtocolError("receiver verified a different transfer digest")
    if result.status != "verified":
        raise RemoteCloneProtocolError("receiver did not verify the destination disk: " + (result.error or "unknown error"))
    return result


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemoteCloneProtocolError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _send_frame(sock: Any, payload: bytes, maximum: int) -> None:
    if not payload or len(payload) > maximum:
        raise RemoteCloneProtocolError("protocol frame is empty or exceeds the configured maximum")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _recv_exact(sock: Any, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sock.recv(count - len(chunks))
        if not chunk:
            raise RemoteCloneProtocolError("peer disconnected before the frame or disk stream completed")
        chunks.extend(chunk)
    return bytes(chunks)


def _recv_frame(sock: Any, maximum: int) -> bytes:
    length = struct.unpack("!I", _recv_exact(sock, 4))[0]
    if length == 0 or length > maximum:
        raise RemoteCloneProtocolError("peer sent an empty or oversized protocol frame")
    return _recv_exact(sock, length)


def send_session_header(sock: Any, header: CloneSessionHeader) -> None:
    payload = json.dumps(header.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    _send_frame(sock, payload, MAX_HEADER_BYTES)


def receive_session_header(sock: Any) -> CloneSessionHeader:
    payload = _recv_frame(sock, MAX_HEADER_BYTES)
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteCloneProtocolError(f"invalid session header JSON: {exc}") from exc
    return CloneSessionHeader.from_dict(value)


def send_terminal_result(sock: Any, result: CloneStreamResult) -> None:
    payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")).encode("ascii")
    _send_frame(sock, payload, MAX_TERMINAL_BYTES)


def receive_terminal_result(sock: Any) -> CloneStreamResult:
    payload = _recv_frame(sock, MAX_TERMINAL_BYTES)
    try:
        value = json.loads(payload.decode("ascii"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteCloneProtocolError(f"invalid terminal result JSON: {exc}") from exc
    return CloneStreamResult.from_dict(value)


def send_disk_stream(
    sock: Any,
    source: BinaryIO,
    expected_size: int,
    *,
    session_id: str,
    chunk_size: int = DEFAULT_CHUNK_BYTES,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    send_terminal: bool = True,
) -> CloneStreamResult:
    """Send exactly expected_size bytes and optionally emit the terminal digest frame."""
    _positive_integer(expected_size, "expected_size")
    _validate_chunk_size(chunk_size)
    digest = hashlib.sha256()
    total = 0
    while total < expected_size:
        if cancel_check is not None and cancel_check():
            raise RemoteCloneCancelled("source operator cancelled the remote clone")
        chunk = source.read(min(chunk_size, expected_size - total))
        if not isinstance(chunk, (bytes, bytearray)) or not chunk:
            raise RemoteCloneProtocolError("source ended before the declared disk byte count")
        if len(chunk) > expected_size - total:
            raise RemoteCloneProtocolError("source returned more bytes than requested")
        sock.sendall(chunk)
        digest.update(chunk)
        total += len(chunk)
        if progress_callback is not None:
            progress_callback(total, expected_size)
    if source.read(1):
        raise RemoteCloneProtocolError("source contains bytes beyond the declared disk size")
    result = CloneStreamResult(session_id, total, digest.hexdigest())
    if send_terminal:
        send_terminal_result(sock, result)
    return result


def receive_disk_stream(
    sock: Any,
    destination: BinaryIO,
    expected_size: int,
    *,
    session_id: str,
    chunk_size: int = DEFAULT_CHUNK_BYTES,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CloneStreamResult:
    """Receive exactly expected_size bytes and verify the session-bound sender digest."""
    _positive_integer(expected_size, "expected_size")
    _validate_chunk_size(chunk_size)
    digest = hashlib.sha256()
    total = 0
    while total < expected_size:
        if cancel_check is not None and cancel_check():
            raise RemoteCloneCancelled("receiver operator cancelled the remote clone")
        chunk = _recv_exact(sock, min(chunk_size, expected_size - total))
        view = memoryview(chunk)
        while view:
            written = destination.write(view)
            if (isinstance(written, bool) or not isinstance(written, int)
                    or written <= 0 or written > len(view)):
                raise RemoteCloneProtocolError("destination writer returned an invalid byte count")
            digest.update(view[:written])
            total += written
            view = view[written:]
            if progress_callback is not None:
                progress_callback(total, expected_size)
    local = CloneStreamResult(session_id, total, digest.hexdigest())
    remote = receive_terminal_result(sock)
    if (remote.session_id != session_id or remote.byte_count != local.byte_count
            or not hmac.compare_digest(remote.sha256, local.sha256)):
        raise RemoteCloneProtocolError("session binding, byte counts or source/receiver SHA-256 digests differ")
    return local


def verify_peer_identity(tls_socket: Any, expected_identity: str) -> None:
    """Require an exact SAN identity or a SHA-256 pin after TLS handshake."""
    _bounded_string(expected_identity, "expected_identity")
    certificate_der = tls_socket.getpeercert(binary_form=True)
    if not certificate_der:
        raise RemoteCloneProtocolError("TLS peer did not present a certificate")
    if expected_identity.startswith("sha256:"):
        expected = expected_identity[7:].lower()
        if not _HEX_SHA256.fullmatch(expected):
            raise RemoteCloneProtocolError("expected SHA-256 certificate pin is malformed")
        actual = hashlib.sha256(certificate_der).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise RemoteCloneProtocolError("TLS peer certificate fingerprint does not match the approved pin")
        return
    certificate = tls_socket.getpeercert()
    if not isinstance(certificate, dict):
        raise RemoteCloneProtocolError("TLS peer certificate details are unavailable")
    kind, separator, value = expected_identity.partition(":")
    if not separator or kind not in {"DNS", "IP", "URI", "EMAIL"} or not value:
        raise RemoteCloneProtocolError("peer identity must use DNS:, IP:, URI:, EMAIL: or sha256: notation")
    if kind == "IP":
        try:
            value = str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise RemoteCloneProtocolError("expected IP peer identity is invalid") from exc
    subject_alt_names = certificate.get("subjectAltName", ())
    matched = any(
        san_kind == {"DNS": "DNS", "IP": "IP Address", "URI": "URI", "EMAIL": "email"}[kind]
        and san_value.lower() == value.lower()
        for san_kind, san_value in subject_alt_names
    )
    if not matched:
        raise RemoteCloneProtocolError("TLS peer certificate does not contain the approved exact SAN identity")


def create_tls_context(
    role: str, *, ca_file: str | None = None,
    certificate_file: str | None = None, private_key_file: str | None = None,
) -> ssl.SSLContext:
    """Create TLS with server-certificate validation and no client authentication."""
    if role == "client":
        if certificate_file is not None or private_key_file is not None:
            raise RemoteCloneProtocolError("Client TLS must not present a client certificate")
        if not ca_file:
            raise RemoteCloneProtocolError("client TLS requires the Server CA certificate")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=ca_file)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = False
    elif role == "server":
        if not certificate_file or not private_key_file:
            raise RemoteCloneProtocolError("server TLS requires its certificate and private key")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.verify_mode = ssl.CERT_NONE
    else:
        raise RemoteCloneProtocolError("TLS role must be 'client' or 'server'")
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if role == "server":
        context.load_cert_chain(certfile=certificate_file, keyfile=private_key_file)
    return context
