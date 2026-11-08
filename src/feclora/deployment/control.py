"""Authenticated Server/Client deployment control plane.

The control channel is TLS 1.3 mutual-authenticated. Certificate SAN identity is
mapped to an explicitly authorized client MAC; MAC is an inventory key only,
never an authenticator. This module coordinates readiness and job arming. It
does not implement the image data plane or execute storage operations.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
import struct
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from feclora.deployment.artifact_transfer import ImageTransferError, receive_image_set, send_image_set
from feclora.deployment.coordinator import (
    ClientState, CoordinatorError, DeploymentCoordinator, JobState,
)
from feclora.deployment.job import DeploymentJob, JobValidationError
from feclora.storage.image_manifest import ImageManifest
from feclora.network.remote_clone_protocol import verify_peer_identity
from feclora.network.tls import connect_mutual_tls

MAX_CONTROL_FRAME = 16 * 1024
_CONTROL_TYPES = {"hello", "job", "ready", "start", "result", "cancel", "error", "transfer_offer", "transfer_ready"}


class DeploymentControlError(RuntimeError):
    """An authenticated deployment control exchange failed."""


def _recv_exact(sock: Any, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        part = sock.recv(count - len(chunks))
        if not part:
            raise DeploymentControlError("peer closed the deployment control channel")
        chunks.extend(part)
    return bytes(chunks)


def send_control_message(sock: Any, payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping) or payload.get("type") not in _CONTROL_TYPES:
        raise DeploymentControlError("invalid deployment control message type")
    try:
        encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise DeploymentControlError(f"control message is not JSON serializable: {exc}") from exc
    if not encoded or len(encoded) > MAX_CONTROL_FRAME:
        raise DeploymentControlError("deployment control message exceeds the frame limit")
    sock.sendall(struct.pack("!I", len(encoded)) + encoded)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeploymentControlError(f"duplicate control message field: {key}")
        result[key] = value
    return result


def receive_control_message(sock: Any, *, expected_type: str | None = None) -> dict[str, Any]:
    length = struct.unpack("!I", _recv_exact(sock, 4))[0]
    if not 1 <= length <= MAX_CONTROL_FRAME:
        raise DeploymentControlError("invalid deployment control frame length")
    try:
        payload = json.loads(
            _recv_exact(sock, length).decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentControlError(f"invalid deployment control JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("type") not in _CONTROL_TYPES:
        raise DeploymentControlError("invalid deployment control message")
    if expected_type is not None and payload["type"] != expected_type:
        raise DeploymentControlError(
            f"expected {expected_type!r} control message, received {payload['type']!r}"
        )
    return payload


def _certificate_identity(sock: Any) -> str:
    certificate = sock.getpeercert()
    if not isinstance(certificate, dict):
        raise DeploymentControlError("client certificate details are unavailable")
    names = certificate.get("subjectAltName", ())
    for kind in ("URI", "DNS", "IP Address", "email"):
        for name_kind, value in names:
            if name_kind == kind and isinstance(value, str) and value:
                prefix = {"IP Address": "IP", "email": "EMAIL"}.get(kind, kind)
                return f"{prefix}:{value}"
    der = sock.getpeercert(binary_form=True)
    if not der:
        raise DeploymentControlError("client did not present a certificate")
    return "sha256:" + hashlib.sha256(der).hexdigest()


@dataclass(frozen=True)
class ReadyClient:
    mac_address: str
    certificate_identity: str
    target_description: str


def _require_tls13_mtls(context: ssl.SSLContext) -> None:
    if (context.verify_mode != ssl.CERT_REQUIRED
            or context.minimum_version != ssl.TLSVersion.TLSv1_3
            or context.maximum_version != ssl.TLSVersion.TLSv1_3):
        raise DeploymentControlError("deployment control requires TLS 1.3 with mandatory peer certificates")


class DeploymentControlServer:
    """Single-job listener adapter around the existing in-memory coordinator."""

    def __init__(
        self,
        coordinator: DeploymentCoordinator,
        tls_context: ssl.SSLContext,
        *,
        local_identity: str,
        client_identity_to_mac: Mapping[str, str],
        firewall: Any = None,
        interface: str | None = None,
    ) -> None:
        _require_tls13_mtls(tls_context)
        if coordinator.job.transport != "unicast":
            raise DeploymentControlError("the authenticated control runtime currently supports unicast jobs only")
        if not isinstance(local_identity, str) or not local_identity or len(local_identity) > 256:
            raise DeploymentControlError("Server certificate identity is required")
        self.coordinator = coordinator
        self.tls_context = tls_context
        self.local_identity = local_identity
        if firewall is not None and not interface:
            raise DeploymentControlError("firewall-scoped control service requires a selected interface")
        self.firewall = firewall
        self.interface = interface
        self._firewall_added: tuple[str, ...] = ()
        self._firewall_opened = False
        self.client_identity_to_mac = {
            identity: mac.lower() for identity, mac in client_identity_to_mac.items()
        }
        if not self.client_identity_to_mac:
            raise DeploymentControlError("at least one certificate-identity-to-MAC mapping is required")
        self._sessions: dict[str, Any] = {}
        self._identities: dict[str, str] = {}
        self._pending_sockets: set[Any] = set()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._listener = None
        self._listener_thread = None
        self.listener_errors: list[str] = []

    @property
    def bound_address(self) -> tuple[str, int] | None:
        if self._listener is None:
            return None
        address = self._listener.getsockname()
        return str(address[0]), int(address[1])

    def start(self, host: str, port: int, *, backlog: int = 16) -> tuple[str, int]:
        """Bind a control listener and accept authenticated clients in a background thread."""
        if self._listener is not None:
            raise DeploymentControlError("deployment control listener is already running")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise DeploymentControlError("deployment control port must be between 0 and 65535")
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError as exc:
            raise DeploymentControlError("control listener bind address must be an IPv4 address") from exc
        if not loopback and (self.firewall is None or not self.interface):
            raise DeploymentControlError("non-loopback control listeners require an interface-scoped firewalld manager")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
            listener.listen(backlog)
            listener.settimeout(1.0)
            if self.firewall is not None:
                port_spec = f"{listener.getsockname()[1]}/tcp"
                if self.firewall.is_open(self.interface):
                    self._firewall_added = self.firewall.add_ports(self.interface, [port_spec])
                else:
                    self.firewall.open(self.interface, [port_spec], include_tftp=False)
                    self._firewall_opened = True
        except Exception as exc:
            listener.close()
            if self._firewall_added and self.firewall is not None:
                self.firewall.remove_ports(self.interface, self._firewall_added)
                self._firewall_added = ()
            if self._firewall_opened and self.firewall is not None:
                self.firewall.close(self.interface)
                self._firewall_opened = False
            raise DeploymentControlError(f"cannot bind deployment control listener: {exc}") from exc
        self._listener = listener
        self._stop_event.clear()
        self._listener_thread = threading.Thread(
            target=self._serve_listener, name="feclora-deployment-control", daemon=True,
        )
        self._listener_thread.start()
        return self.bound_address  # type: ignore[return-value]

    def _serve_listener(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.accept_ready_client(self._listener)
            except (socket.timeout, TimeoutError):
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    self.listener_errors.append(str(exc))
            except Exception as exc:
                if not self._stop_event.is_set():
                    self.listener_errors.append(str(exc))

    def stop(self) -> None:
        """Stop accepting peers and close any remaining control sessions."""
        self._stop_event.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=3)
            self._listener_thread = None
        with self._lock:
            pending = tuple(self._pending_sockets)
            self._pending_sockets.clear()
            sessions = tuple(self._sessions.items())
            self._sessions.clear()
        for pending_socket in pending:
            try:
                pending_socket.close()
            except OSError:
                pass
        for mac, tls_socket in sessions:
            try:
                record = next((item for item in self.coordinator.clients() if item.mac_address == mac), None)
                if record is not None and record.state not in {
                    ClientState.SUCCEEDED, ClientState.FAILED, ClientState.DISCONNECTED,
                }:
                    self.coordinator.disconnect_client(mac, "Server control service stopped")
            except CoordinatorError:
                pass
            try:
                tls_socket.close()
            except OSError:
                pass

        if self.firewall is not None and self.interface:
            try:
                if self._firewall_added:
                    self.firewall.remove_ports(self.interface, self._firewall_added)
                    self._firewall_added = ()
                if self._firewall_opened:
                    self.firewall.close(self.interface)
                    self._firewall_opened = False
            except Exception as exc:
                self.listener_errors.append(f"firewall cleanup failed: {exc}")

    def accept_ready_client(self, listener: Any) -> ReadyClient:
        accepted, _address = listener.accept()
        tls_socket = None
        registered_mac = None
        with self._lock:
            self._pending_sockets.add(accepted)
        try:
            accepted.settimeout(30)
            tls_socket = self.tls_context.wrap_socket(accepted, server_side=True)
            with self._lock:
                self._pending_sockets.discard(accepted)
                self._pending_sockets.add(tls_socket)
            tls_socket.settimeout(120)
            identity = _certificate_identity(tls_socket)
            mac = self.client_identity_to_mac.get(identity)
            if mac is None:
                raise DeploymentControlError("client certificate identity is not enrolled for this deployment")
            verify_peer_identity(tls_socket, identity)
            hello = receive_control_message(tls_socket, expected_type="hello")
            if set(hello) != {"type", "job_id", "mac_address", "certificate_identity"}:
                raise DeploymentControlError("client hello contains missing or unknown fields")
            if (hello["job_id"] != self.coordinator.job.job_id or hello["mac_address"] != mac
                    or hello["certificate_identity"] != identity):
                raise DeploymentControlError("client hello does not match the enrolled identity and active job")
            self.coordinator.register_client(mac, authenticated=True)
            registered_mac = mac
            send_control_message(tls_socket, {
                "type": "job", "job": self.coordinator.job.to_dict(),
                "server_identity": self.local_identity,
            })
            ready = receive_control_message(tls_socket, expected_type="ready")
            if set(ready) != {"type", "job_id", "target_description", "locally_authorized"}:
                raise DeploymentControlError("client readiness contains missing or unknown fields")
            description = ready["target_description"]
            if (ready["job_id"] != self.coordinator.job.job_id
                    or ready["locally_authorized"] is not True
                    or not isinstance(description, str) or not description
                    or len(description) > 256 or "/dev/" in description or any(ord(c) < 32 for c in description)):
                raise DeploymentControlError("client has not supplied valid local target authorization")
            self.coordinator.mark_ready(mac)
            with self._lock:
                self._pending_sockets.discard(tls_socket)
                self._sessions[mac] = tls_socket
                self._identities[mac] = identity
            return ReadyClient(mac, identity, description)
        except Exception as exc:
            if registered_mac is not None:
                try:
                    self.coordinator.disconnect_client(registered_mac, f"control handshake failed: {exc}")
                except CoordinatorError:
                    pass
            with self._lock:
                self._pending_sockets.discard(accepted)
                if tls_socket is not None:
                    self._pending_sockets.discard(tls_socket)
            if tls_socket is not None:
                tls_socket.close()
            else:
                accepted.close()
            raise

    def arm_and_start(self) -> tuple[str, ...]:
        """Arm only through the coordinator, then notify every authenticated READY client."""
        self.coordinator.arm()
        started: list[str] = []
        with self._lock:
            sessions = tuple(self._sessions.items())
        for mac, tls_socket in sessions:
            try:
                self.coordinator.mark_running(mac)
                send_control_message(tls_socket, {
                    "type": "start", "job_id": self.coordinator.job.job_id,
                    "operation": self.coordinator.job.operation,
                    "image_id": self.coordinator.job.image_id,
                })
                started.append(mac)
            except (OSError, DeploymentControlError, CoordinatorError) as exc:
                try:
                    self.coordinator.disconnect_client(mac, f"could not start client: {exc}")
                except CoordinatorError:
                    pass
                tls_socket.close()
        return tuple(started)

    def _running_session(self, mac_address: str, operation: str) -> Any:
        if self.coordinator.job.operation != operation:
            raise DeploymentControlError(f"job operation must be {operation!r}")
        record = next(
            (item for item in self.coordinator.clients() if item.mac_address == mac_address.lower()),
            None,
        )
        if record is None or record.state is not ClientState.RUNNING:
            raise DeploymentControlError("client must be authenticated, READY and STARTed before image transfer")
        with self._lock:
            tls_socket = self._sessions.get(mac_address.lower())
        if tls_socket is None:
            raise DeploymentControlError("client has no active authenticated control session")
        return tls_socket

    def _record_transfer_failure(self, mac_address: str, detail: str) -> None:
        try:
            self.coordinator.report_result(mac_address, success=False, detail=detail[:512])
        except CoordinatorError:
            try:
                self.coordinator.disconnect_client(mac_address, detail[:512])
            except CoordinatorError:
                pass
        with self._lock:
            tls_socket = self._sessions.get(mac_address.lower())
        if tls_socket is not None:
            try:
                tls_socket.close()
            except OSError:
                pass

    def send_restore_image(
        self,
        mac_address: str,
        repository: str,
        manifest_path: str,
        *,
        trusted_public_key: str,
    ) -> ImageManifest:
        """Send the job's signed image set to one authenticated running restore client."""
        tls_socket = self._running_session(mac_address, "restore")
        try:
            tls_socket.settimeout(86400)
            send_control_message(tls_socket, {
                "type": "transfer_offer", "job_id": self.coordinator.job.job_id,
                "image_id": self.coordinator.job.image_id,
            })
            return send_image_set(
                tls_socket, repository, manifest_path,
                expected_image_id=self.coordinator.job.image_id,
                trusted_public_key=trusted_public_key,
            )
        except (ImageTransferError, OSError, DeploymentControlError) as exc:
            self._record_transfer_failure(mac_address, f"restore image transfer failed: {exc}")
            if isinstance(exc, DeploymentControlError):
                raise
            raise DeploymentControlError(f"restore image transfer failed: {exc}") from exc

    def receive_saved_image(
        self,
        mac_address: str,
        repository: str,
        *,
        trusted_public_key: str,
    ) -> str:
        """Receive a signed image set from one authenticated running save client."""
        tls_socket = self._running_session(mac_address, "save")
        try:
            tls_socket.settimeout(86400)
            transfer = receive_control_message(tls_socket)
            if transfer.get("type") == "result":
                if (set(transfer) != {"type", "job_id", "success", "detail"}
                        or transfer.get("job_id") != self.coordinator.job.job_id
                        or transfer.get("success") is not False
                        or not isinstance(transfer.get("detail"), str)
                        or len(transfer["detail"]) > 512):
                    raise DeploymentControlError("client failure result is invalid")
                self.coordinator.report_result(
                    mac_address, success=transfer["success"], detail=transfer["detail"],
                )
                return ""
            if (set(transfer) != {"type", "job_id", "image_id"}
                    or transfer.get("type") != "transfer_ready"
                    or transfer.get("job_id") != self.coordinator.job.job_id
                    or transfer.get("image_id") != self.coordinator.job.image_id):
                raise DeploymentControlError("client image-transfer readiness is not bound to this job")
            return receive_image_set(
                tls_socket, repository,
                expected_image_id=self.coordinator.job.image_id,
                trusted_public_key=trusted_public_key,
            )
        except (ImageTransferError, OSError, DeploymentControlError) as exc:
            self._record_transfer_failure(mac_address, f"saved image transfer failed: {exc}")
            if isinstance(exc, DeploymentControlError):
                raise
            raise DeploymentControlError(f"saved image transfer failed: {exc}") from exc

    def collect_results(self, *, timeout: float = 3600) -> dict[str, str]:
        results: dict[str, str] = {}
        with self._lock:
            sessions = tuple(self._sessions.items())
        for mac, tls_socket in sessions:
            record = next(
                (item for item in self.coordinator.clients() if item.mac_address == mac), None,
            )
            if record is not None and record.state in {
                ClientState.SUCCEEDED, ClientState.FAILED, ClientState.DISCONNECTED,
            }:
                tls_socket.close()
                results[mac] = record.state.value
                continue
            try:
                tls_socket.settimeout(timeout)
                message = receive_control_message(tls_socket, expected_type="result")
                if set(message) != {"type", "job_id", "success", "detail"}:
                    raise DeploymentControlError("client result contains missing or unknown fields")
                if message["job_id"] != self.coordinator.job.job_id:
                    raise DeploymentControlError("client result belongs to another job")
                if not isinstance(message["success"], bool):
                    raise DeploymentControlError("client result success flag must be boolean")
                detail = message["detail"]
                if not isinstance(detail, str) or len(detail) > 512:
                    raise DeploymentControlError("client result detail is invalid")
                self.coordinator.report_result(mac, success=message["success"], detail=detail)
                results[mac] = "succeeded" if message["success"] else "failed"
            except (OSError, DeploymentControlError, CoordinatorError, TimeoutError) as exc:
                try:
                    self.coordinator.disconnect_client(mac, f"result not received: {exc}")
                except CoordinatorError:
                    pass
                results[mac] = "disconnected"
            finally:
                tls_socket.close()
        return results

    def cancel(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for tls_socket in sessions:
            try:
                send_control_message(tls_socket, {
                    "type": "cancel", "job_id": self.coordinator.job.job_id,
                })
            except (OSError, DeploymentControlError):
                pass
            tls_socket.close()
        if self.coordinator.state not in {
            JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED,
        }:
            self.coordinator.cancel()


def join_deployment(
    host: str,
    port: int,
    tls_context: ssl.SSLContext,
    *,
    local_identity: str,
    expected_server_identity: str,
    mac_address: str,
    job_id: str,
    prepare_local_target: Callable[[DeploymentJob], str],
    execute_job: Callable[[DeploymentJob, Any], tuple[bool, str]],
    timeout: float = 120,
) -> tuple[DeploymentJob, bool, str]:
    """Authenticate, receive a job, obtain local target approval, then execute on START."""
    _require_tls13_mtls(tls_context)
    if not isinstance(local_identity, str) or not local_identity or len(local_identity) > 256:
        raise DeploymentControlError("local certificate identity is required")
    if not isinstance(mac_address, str) or not mac_address or len(mac_address) > 32:
        raise DeploymentControlError("client MAC address is required")
    if not isinstance(job_id, str) or not job_id or len(job_id) > 64:
        raise DeploymentControlError("deployment job UUID is required")
    tls_socket = connect_mutual_tls(
        tls_context, host, port, expected_peer_identity=expected_server_identity,
        timeout=15, io_timeout=timeout,
    )
    with tls_socket:
        send_control_message(tls_socket, {
            "type": "hello", "job_id": job_id, "mac_address": mac_address.lower(),
            "certificate_identity": local_identity,
        })
        offer = receive_control_message(tls_socket, expected_type="job")
        if set(offer) != {"type", "job", "server_identity"}:
            raise DeploymentControlError("server job offer contains missing or unknown fields")
        if offer["server_identity"] != expected_server_identity:
            raise DeploymentControlError("job offer is not bound to the authenticated server identity")
        try:
            job = DeploymentJob.from_dict(offer["job"])
        except (JobValidationError, TypeError) as exc:
            raise DeploymentControlError(f"server supplied an invalid deployment job: {exc}") from exc
        if job.transport != "unicast":
            raise DeploymentControlError("Client currently supports authenticated unicast jobs only")
        if job.job_id != job_id or not job.authorizes_client(mac_address):
            raise DeploymentControlError("job does not authorize this client identity")
        target_description = prepare_local_target(job)
        if (not isinstance(target_description, str) or not target_description
                or len(target_description) > 256 or "/dev/" in target_description or any(ord(c) < 32 for c in target_description)):
            raise DeploymentControlError("local target approval callback returned an invalid description")
        send_control_message(tls_socket, {
            "type": "ready", "job_id": job.job_id,
            "target_description": target_description, "locally_authorized": True,
        })
        start = receive_control_message(tls_socket)
        if start.get("type") == "cancel":
            if set(start) != {"type", "job_id"} or start.get("job_id") != job.job_id:
                raise DeploymentControlError("server cancellation is not bound to this job")
            raise DeploymentControlError("server cancelled the deployment before start")
        if set(start) != {"type", "job_id", "operation", "image_id"}:
            raise DeploymentControlError("server start command contains missing or unknown fields")
        if start.get("type") != "start" or start.get("job_id") != job.job_id:
            raise DeploymentControlError("server did not arm this deployment job")
        if start.get("operation") != job.operation or start.get("image_id") != job.image_id:
            raise DeploymentControlError("server start command does not match the authorized job")
        try:
            success, detail = execute_job(job, tls_socket)
        except Exception as exc:
            success, detail = False, str(exc)
        if not isinstance(success, bool) or not isinstance(detail, str):
            success, detail = False, "client execution callback returned an invalid result"
        send_control_message(tls_socket, {
            "type": "result", "job_id": job.job_id,
            "success": success, "detail": detail[:512],
        })
        return job, success, detail[:512]
