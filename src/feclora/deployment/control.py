"""Authenticated Server/Client deployment control plane.

The control channel is TLS 1.3 mutual-authenticated. Certificate SAN identity is
mapped to an explicitly authorized client MAC; MAC is an inventory key only,
never an authenticator. This module coordinates readiness and job arming,
unicast TLS image transfer, and multicast UDPcast artifact delivery. It does not
execute block-device writes; the Client runtime performs protected staging,
verification and restore.
"""
from __future__ import annotations

import base64
import hashlib
import os
import ipaddress
import json
import posixpath
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
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.image_security import ImageSecurityError, verify_manifest_signature
from feclora.network.udpcast import UDPcastConfig, UDPcastError, send_multicast_artifact, verify_artifact_file
from feclora.network.remote_clone_protocol import verify_peer_identity
from feclora.network.firewall import PXEFirewallError
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


@dataclass(frozen=True)
class LocalTargetApproval:
    """Client-local target choice and typed confirmation; never serialized to Server."""
    device_path: str
    description: str
    confirmation: str


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
        self._firewall_state_callback: Callable[[dict[str, Any] | None], None] | None = None
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

    def start(
        self, host: str, port: int, *, backlog: int = 16,
        firewall_state_callback: Callable[[dict[str, Any] | None], None] | None = None,
    ) -> tuple[str, int]:
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
                self._firewall_state_callback = firewall_state_callback
                if firewall_state_callback is not None:
                    firewall_state_callback({
                        "interface": self.interface,
                        "firewall": self.firewall.export_state(self.interface),
                        "opened_by_service": self._firewall_opened,
                        "added_ports": list(self._firewall_added),
                    })
        except Exception as exc:
            listener.close()
            if self._firewall_added and self.firewall is not None:
                self.firewall.remove_ports(self.interface, self._firewall_added)
                self._firewall_added = ()
            if self._firewall_opened and self.firewall is not None:
                self.firewall.close(self.interface)
                self._firewall_opened = False
            if firewall_state_callback is not None:
                try:
                    firewall_state_callback(None)
                except Exception:
                    pass
            self._firewall_state_callback = None
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
        """Stop accepting peers and close pending and established control sessions."""
        self._stop_event.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        with self._lock:
            pending = tuple(self._pending_sockets)
            self._pending_sockets.clear()
        for pending_socket in pending:
            try:
                pending_socket.close()
            except OSError:
                pass
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=3)
            self._listener_thread = None
        with self._lock:
            sessions = tuple(self._sessions.items())
            self._sessions.clear()
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
        cleanup_error = None
        if self.firewall is not None and self.interface:
            try:
                if self._firewall_added:
                    self.firewall.remove_ports(self.interface, self._firewall_added)
                    self._firewall_added = ()
                if self._firewall_opened:
                    self.firewall.close(self.interface)
                    self._firewall_opened = False
            except Exception as exc:
                cleanup_error = exc
                self.listener_errors.append(f"firewall cleanup failed: {exc}")
        if cleanup_error is not None:
            raise DeploymentControlError(f"control firewall cleanup failed: {cleanup_error}") from cleanup_error
        if self._firewall_state_callback is not None:
            try:
                self._firewall_state_callback(None)
            finally:
                self._firewall_state_callback = None

    def accept_ready_client(self, listener: Any) -> ReadyClient | None:
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
            hello = receive_control_message(tls_socket)
            if set(hello) != {"type", "job_id", "mac_address", "certificate_identity"}:
                raise DeploymentControlError("client hello contains missing or unknown fields")
            if (hello["job_id"] != self.coordinator.job.job_id or hello["mac_address"] != mac
                    or hello["certificate_identity"] != identity):
                raise DeploymentControlError("client hello does not match the enrolled identity and active job")
            if hello["type"] == "inspect":
                send_control_message(tls_socket, {
                    "type": "job", "job": self.coordinator.job.to_dict(),
                    "server_identity": self.local_identity,
                })
                tls_socket.close()
                with self._lock:
                    self._pending_sockets.discard(tls_socket)
                return None
            if hello["type"] != "hello":
                raise DeploymentControlError("client message must be hello or inspect")
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

    def run_one_client_job(
        self,
        repository: str,
        *,
        trusted_public_key: str,
        manifest_path: str | None = None,
        result_timeout: float = 86400,
    ) -> dict[str, str]:
        """Arm and run one authenticated unicast save/restore job end to end."""
        if self.coordinator.job.transport != "unicast":
            raise DeploymentControlError("run_one_client_job only accepts unicast jobs")
        clients = self.coordinator.clients()
        if len(clients) != 1 or clients[0].state is not ClientState.READY:
            raise DeploymentControlError("initial unicast runtime requires exactly one authenticated READY client")
        mac = clients[0].mac_address
        if self.coordinator.job.operation == "restore" and not manifest_path:
            raise DeploymentControlError("restore job requires the signed image manifest path")
        started = self.arm_and_start()
        if started != (mac,):
            return self.collect_results(timeout=result_timeout)
        try:
            if self.coordinator.job.operation == "restore":
                self.send_restore_image(
                    mac, repository, manifest_path,
                    trusted_public_key=trusted_public_key,
                )
            else:
                self.receive_saved_image(
                    mac, repository, trusted_public_key=trusted_public_key,
                )
        except (DeploymentControlError, ImageTransferError):
            # The transfer method records a terminal failed result and closes
            # the session; collect_results returns that recorded state.
            pass
        return self.collect_results(timeout=result_timeout)

    def run_multicast_restore_job(
        self,
        repository: str,
        manifest_path: str,
        *,
        trusted_public_key: str,
        udpcast_config: UDPcastConfig,
        result_timeout: float = 86400,
    ) -> dict[str, str]:
        """Restore one signed image to all enrolled READY Clients over UDPcast."""
        job = self.coordinator.job
        if job.transport != "multicast" or job.operation != "restore":
            raise DeploymentControlError("multicast runtime supports restore jobs only")
        if (udpcast_config.interface != job.network_interface
                or udpcast_config.data_group != job.multicast_group
                or udpcast_config.portbase != job.multicast_port):
            raise DeploymentControlError("UDPcast configuration does not match the authenticated job")
        clients = self.coordinator.clients()
        if (len(clients) != len(job.authorized_clients)
                or {item.mac_address for item in clients} != set(job.authorized_clients)
                or any(item.state is not ClientState.READY for item in clients)):
            raise DeploymentControlError("every authorized Client must be authenticated and READY before multicast arming")
        if udpcast_config.min_receivers != len(clients):
            raise DeploymentControlError("UDPcast receiver threshold must equal the enrolled READY Client count")
        signature_path = manifest_path + ".minisig"
        try:
            verify_manifest_signature(manifest_path, trusted_public_key)
            with open(manifest_path, "rb") as stream:
                manifest_bytes = stream.read(8 * 1024 + 1)
            with open(signature_path, "rb") as stream:
                signature_bytes = stream.read(2048 + 1)
            if len(manifest_bytes) > 8 * 1024 or len(signature_bytes) > 2048:
                raise DeploymentControlError("signed manifest exceeds the multicast control-plane size limit")
            manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
            if manifest.image_id != job.image_id:
                raise DeploymentControlError("signed manifest image identifier does not match the multicast job")
            if manifest.image_type != job.target_type:
                raise DeploymentControlError("signed manifest image type does not match the multicast job target type")
            if not manifest.artifacts or any(artifact.encryption != "age" for artifact in manifest.artifacts):
                raise DeploymentControlError("multicast restore requires every artifact to be age-encrypted for the authorized Clients")
            for artifact in manifest.artifacts:
                verify_artifact_file(os.path.join(repository, artifact.filename), artifact)
        except (OSError, UnicodeError, ManifestValidationError, ImageSecurityError, UDPcastError) as exc:
            raise DeploymentControlError(f"cannot verify multicast image manifest: {exc}") from exc
        expected_macs = tuple(sorted(job.authorized_clients))
        started = self.arm_and_start()
        if tuple(sorted(started)) != expected_macs:
            raise DeploymentControlError("not every authorized Client accepted the multicast START")
        offer = {
            "type": "transfer_offer",
            "job_id": job.job_id,
            "image_id": job.image_id,
            "manifest_b64": base64.b64encode(manifest_bytes).decode("ascii"),
            "signature_b64": base64.b64encode(signature_bytes).decode("ascii"),
        }
        with self._lock:
            sessions = tuple((mac, self._sessions.get(mac)) for mac in expected_macs)
        try:
            for mac, tls_socket in sessions:
                if tls_socket is None:
                    raise DeploymentControlError(f"Client {mac} lost its authenticated control session")
                send_control_message(tls_socket, offer)
            for artifact in manifest.artifacts:
                source_path = os.path.join(repository, artifact.filename)
                send_multicast_artifact(
                    self.coordinator, source_path, manifest_path,
                    trusted_public_key, udpcast_config, firewall=self.firewall,
                )
        except (OSError, DeploymentControlError, UDPcastError, ImageSecurityError, PXEFirewallError) as exc:
            for mac, _tls_socket in sessions:
                self._record_transfer_failure(mac, f"multicast restore failed: {exc}")
            raise DeploymentControlError(f"multicast restore transfer failed: {exc}") from exc
        return self.collect_results(timeout=result_timeout)

    def collect_results(self, *, timeout: float = 86400) -> dict[str, str]:
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
        # Persist the terminal transition before telling peers to stop.
        self.coordinator.cancel()
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



def inspect_deployment_job(
    host: str,
    port: int,
    tls_context: ssl.SSLContext,
    *,
    local_identity: str,
    expected_server_identity: str,
    mac_address: str,
    job_id: str,
    timeout: float = 15,
) -> DeploymentJob:
    """Read an authorized job offer without registering a Client or becoming READY."""
    _require_tls13_mtls(tls_context)
    if not isinstance(local_identity, str) or not local_identity or len(local_identity) > 256:
        raise DeploymentControlError("local certificate identity is required")
    if not isinstance(mac_address, str) or not mac_address or len(mac_address) > 32:
        raise DeploymentControlError("client MAC address is required")
    if not isinstance(job_id, str) or not job_id or len(job_id) > 64:
        raise DeploymentControlError("deployment job UUID is required")
    tls_socket = connect_mutual_tls(
        tls_context, host, port, expected_peer_identity=expected_server_identity,
        timeout=timeout, io_timeout=timeout,
    )
    with tls_socket:
        send_control_message(tls_socket, {
            "type": "inspect", "job_id": job_id, "mac_address": mac_address.lower(),
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
        if job.job_id != job_id or not job.authorizes_client(mac_address):
            raise DeploymentControlError("job does not authorize this Client identity")
        if job.transport == "multicast" and job.operation != "restore":
            raise DeploymentControlError("multicast Client jobs currently support restore only")
        return job


def join_deployment(
    host: str,
    port: int,
    tls_context: ssl.SSLContext,
    *,
    local_identity: str,
    expected_server_identity: str,
    mac_address: str,
    job_id: str,
    prepare_local_target: Callable[[DeploymentJob], LocalTargetApproval],
    execute_job: Callable[[DeploymentJob, Any, LocalTargetApproval], tuple[bool, str]],
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
        if job.transport == "multicast" and job.operation != "restore":
            raise DeploymentControlError("multicast Client jobs currently support restore only")
        if job.job_id != job_id or not job.authorizes_client(mac_address):
            raise DeploymentControlError("job does not authorize this client identity")
        approval = prepare_local_target(job)
        if not isinstance(approval, LocalTargetApproval):
            raise DeploymentControlError("local target callback must return a LocalTargetApproval")
        device_path = approval.device_path
        if (not isinstance(device_path, str) or not device_path.startswith("/dev/")
                or len(device_path) > 256 or posixpath.normpath(device_path) != device_path
                or "//" in device_path or any(ord(c) < 32 for c in device_path)):
            raise DeploymentControlError("local target approval contains an invalid device path")
        description = approval.description
        if (not isinstance(description, str) or not description
                or len(description) > 256 or "/dev/" in description
                or any(ord(c) < 32 for c in description)):
            raise DeploymentControlError("local target approval contains an invalid description")
        required_confirmation = (
            f"ERASE {device_path} FROM {expected_server_identity}"
            if job.operation == "restore"
            else f"READ {device_path} TO {expected_server_identity}"
        )
        if approval.confirmation != required_confirmation:
            raise DeploymentControlError("local typed target confirmation does not match the selected device and Server")
        send_control_message(tls_socket, {
            "type": "ready", "job_id": job.job_id,
            "target_description": description, "locally_authorized": True,
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
            success, detail = execute_job(job, tls_socket, approval)
        except Exception as exc:
            success, detail = False, str(exc)
        if not isinstance(success, bool) or not isinstance(detail, str):
            success, detail = False, "client execution callback returned an invalid result"
        send_control_message(tls_socket, {
            "type": "result", "job_id": job.job_id,
            "success": success, "detail": detail[:512],
        })
        return job, success, detail[:512]
