"""Authenticated Server/Client deployment control plane.

The control channel uses TLS to authenticate the Server certificate to Clients.
Clients do not present certificates or authenticate individually. The reported
MAC is checked only for membership in the active job; it is not an authenticator.
This module coordinates readiness and job arming,
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
import re
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from feclora.deployment.artifact_transfer import ImageTransferError, receive_image_set, send_image_set
from feclora.deployment.coordinator import (
    ClientState, CoordinatorError, DeploymentCoordinator, JobState,
)
from feclora.deployment.job import DeploymentJob, JobValidationError
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.network.udpcast import UDPcastConfig, UDPcastError, send_multicast_artifact, verify_artifact_file
from feclora.network.firewall import PXEFirewallError
from feclora.network.tls import accept_tls, connect_tls
from feclora.network.remote_clone import build_remote_clone_header, send_remote_disk

MAX_CONTROL_FRAME = 16 * 1024
_CONTROL_TYPES = {"hello", "inspect", "job", "ready", "start", "result", "cancel", "error", "transfer_offer", "transfer_ready", "progress", "physical_ready"}


class DeploymentControlError(RuntimeError):
    """A deployment control exchange failed."""


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


@dataclass(frozen=True)
class ReadyClient:
    mac_address: str
    target_description: str
    target_device: str | None = None
    physical_identity: Mapping[str, Any] | None = None

@dataclass(frozen=True)
class LocalTargetApproval:
    """Client-local target choice and typed confirmation; never serialized to Server."""
    device_path: str
    description: str
    confirmation: str
    physical_identity: Mapping[str, Any] | None = None
    physical_stream: Mapping[str, Any] | None = None


class DeploymentControlServer:
    """Single-job listener accepting Clients without client certificate authentication."""

    def __init__(
        self,
        coordinator: DeploymentCoordinator,
        tls_context: ssl.SSLContext,
        *,
        local_identity: str,
        firewall: Any = None,
        interface: str | None = None,
        progress_event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
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
        self._sessions: dict[str, Any] = {}
        self._target_devices: dict[str, str] = {}
        self._target_identities: dict[str, dict[str, Any]] = {}
        self._progress: dict[str, dict[str, Any]] = {}
        self._progress_event_sink = progress_event_sink
        self._last_persisted_progress: dict[str, dict[str, Any]] = {}
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
        """Bind a control listener and accept Clients over server-authenticated TLS."""
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

    def _record_listener_error(self, message: object) -> None:
        """Keep rejected connection failures from growing memory without bound."""
        with self._lock:
            self.listener_errors.append(str(message)[:512])
            if len(self.listener_errors) > 64:
                del self.listener_errors[:-64]

    def _serve_listener(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.accept_ready_client(self._listener)
            except (socket.timeout, TimeoutError):
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    self._record_listener_error(exc)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._record_listener_error(exc)

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
                self._record_listener_error(f"firewall cleanup failed: {exc}")
        callback = self._firewall_state_callback
        self._firewall_state_callback = None
        if cleanup_error is not None:
            # Keep the persisted ownership record on disk when cleanup failed:
            # recovery must still know that this service may own an open zone.
            raise DeploymentControlError(f"control firewall cleanup failed: {cleanup_error}") from cleanup_error
        if callback is not None:
            callback(None)

    def accept_ready_client(self, listener: Any) -> ReadyClient | None:
        accepted, _address = listener.accept()
        tls_socket = None
        registered_mac = None
        with self._lock:
            # stop() sets the event before taking this lock and draining the
            # pending set. This closes the accept-vs-stop race without leaving
            # a newly accepted socket outside shutdown's ownership.
            if self._stop_event.is_set():
                accepted.close()
                return None
            self._pending_sockets.add(accepted)
        try:
            accepted.settimeout(30)
            tls_socket = accept_tls(self.tls_context, accepted)
            with self._lock:
                self._pending_sockets.discard(accepted)
                if self._stop_event.is_set():
                    tls_socket.close()
                    return None
                self._pending_sockets.add(tls_socket)
            tls_socket.settimeout(120)
            hello = receive_control_message(tls_socket)
            if set(hello) != {"type", "job_id", "mac_address"}:
                raise DeploymentControlError("client hello contains missing or unknown fields")
            mac = hello["mac_address"]
            if (not isinstance(mac, str) or len(mac) > 32
                    or hello["job_id"] != self.coordinator.job.job_id):
                raise DeploymentControlError("client hello does not match the active deployment job")
            mac = mac.lower()
            if not self.coordinator.job.authorizes_client(mac):
                raise DeploymentControlError("Client MAC is not selected for this deployment job")
            if hello["type"] == "inspect":
                if self.coordinator.state.value != "created":
                    raise DeploymentControlError("Server job no longer accepts Client inspection or admission")
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
            self.coordinator.register_client(mac)
            registered_mac = mac
            send_control_message(tls_socket, {
                "type": "job", "job": self.coordinator.job.to_dict(),
                "server_identity": self.local_identity,
            })
            ready = receive_control_message(tls_socket, expected_type="ready")
            expected_fields = {"type", "job_id", "target_description", "locally_authorized"}
            if self.coordinator.job.operation == "clone":
                expected_fields.add("target_device")
                if self.coordinator.job.transport == "multicast":
                    expected_fields.add("target_identity")
            if set(ready) != expected_fields:
                raise DeploymentControlError("client readiness contains missing or unknown fields")
            description = ready["target_description"]
            target_device = ready.get("target_device")
            if (ready["job_id"] != self.coordinator.job.job_id
                    or ready["locally_authorized"] is not True
                    or not isinstance(description, str) or not description
                    or len(description) > 256 or "/dev/" in description or any(ord(c) < 32 for c in description)):
                raise DeploymentControlError("client has not supplied valid local target authorization")
            target_identity = ready.get("target_identity")
            if self.coordinator.job.operation == "clone" and self.coordinator.job.transport == "multicast" and (
                not isinstance(target_identity, dict) or set(target_identity) != {
                    "path", "major_minor", "sysfs_path", "wwn", "serial", "size_bytes",
                    "logical_sector_size", "physical_sector_size", "read_only", "mountpoints",
                    "holders", "backs_system", "busy",
                }
            ):
                raise DeploymentControlError("Client physical destination identity is incomplete")
            if self.coordinator.job.operation == "clone" and (
                not isinstance(target_device, str) or not target_device.startswith("/dev/")
                or len(target_device) > 256 or posixpath.normpath(target_device) != target_device
                or "//" in target_device or any(ord(c) < 32 for c in target_device)
            ):
                raise DeploymentControlError("Client clone target device path is invalid")
            self.coordinator.mark_ready(mac)
            with self._lock:
                if self._stop_event.is_set():
                    raise DeploymentControlError("Server control service stopped during Client admission")
                self._pending_sockets.discard(tls_socket)
                self._sessions[mac] = tls_socket
                if target_device is not None:
                    self._target_devices[mac] = target_device
                if target_identity is not None:
                    self._target_identities[mac] = dict(target_identity)
            return ReadyClient(mac, description, target_device, target_identity)
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

    def arm_and_start(self, *, physical_stream: Mapping[str, Any] | None = None) -> tuple[str, ...]:
        """Arm only through the coordinator, then notify every READY Client."""
        self.coordinator.arm()
        started: list[str] = []
        with self._lock:
            sessions = tuple(self._sessions.items())
        for mac, tls_socket in sessions:
            try:
                self.coordinator.mark_running(mac)
                start_message = {
                    "type": "start", "job_id": self.coordinator.job.job_id,
                    "operation": self.coordinator.job.operation,
                    "image_id": self.coordinator.job.image_id,
                }
                if physical_stream is not None:
                    start_message["physical_stream"] = dict(physical_stream)
                send_control_message(tls_socket, start_message)
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
            raise DeploymentControlError("client must be READY and STARTed before image transfer")
        with self._lock:
            tls_socket = self._sessions.get(mac_address.lower())
        if tls_socket is None:
            raise DeploymentControlError("client has no active control session")
        return tls_socket

    def _record_client_progress(self, mac_address: str, message: dict[str, Any]) -> None:
        """Validate and retain a progress frame received on the Server-authenticated TLS session."""
        expected = {"type", "job_id", "phase", "completed_bytes", "total_bytes"}
        if set(message) != expected or message.get("type") != "progress":
            raise DeploymentControlError("client progress frame has missing or unknown fields")
        if message.get("job_id") != self.coordinator.job.job_id:
            raise DeploymentControlError("client progress belongs to another deployment job")
        if message.get("phase") not in {"save", "restore", "transfer"}:
            raise DeploymentControlError("client progress phase is invalid")
        if message["phase"] != "transfer" and message["phase"] != self.coordinator.job.operation:
            raise DeploymentControlError("client disk-I/O progress phase does not match the deployment operation")
        completed = message.get("completed_bytes")
        total = message.get("total_bytes")
        if (isinstance(completed, bool) or not isinstance(completed, int) or completed < 0
                or (total is not None and (
                    isinstance(total, bool) or not isinstance(total, int)
                    or total < 0 or completed > total
                ))):
            raise DeploymentControlError("client progress byte counters are invalid")
        mac = mac_address.lower()
        record = next((item for item in self.coordinator.clients() if item.mac_address == mac), None)
        if record is None or record.state is not ClientState.RUNNING:
            raise DeploymentControlError("progress is accepted only on a running Client session for this job")
        now = time.monotonic()
        with self._lock:
            previous = self._progress.get(mac)
            if (previous is not None and previous["phase"] == message["phase"]
                    and completed < previous["completed_bytes"]):
                raise DeploymentControlError("Client progress byte counter moved backwards")
            rate = 0.0
            if (previous is not None and previous["phase"] == message["phase"]
                    and now > previous["monotonic"]):
                rate = (completed - previous["completed_bytes"]) / (now - previous["monotonic"])
            updated_at = datetime.now(timezone.utc).isoformat()
            snapshot = {
                "phase": message["phase"], "completed_bytes": completed,
                "total_bytes": total, "bytes_per_second": round(rate, 1),
                "updated_at": updated_at,
            }
            progress_sink = getattr(self, "_progress_event_sink", None)
            last_persisted = getattr(self, "_last_persisted_progress", {})
            previous_saved = last_persisted.get(mac)
            should_persist = (
                progress_sink is not None
                and (
                    previous_saved is None
                    or previous_saved["phase"] != snapshot["phase"]
                    or previous_saved["total_bytes"] != total
                    or completed - previous_saved["completed_bytes"] >= 1024 * 1024
                    or now - previous_saved["monotonic"] >= 5.0
                    or (
                        total is not None and completed == total
                        and previous_saved["completed_bytes"] != completed
                    )
                )
            )
            if should_persist:
                try:
                    progress_sink({
                        "timestamp": updated_at,
                        "job_id": self.coordinator.job.job_id,
                        "event": "client_progress",
                        "job_state": self.coordinator.state.value,
                        "client_mac": mac,
                        "client_state": ClientState.RUNNING.value,
                        "progress": snapshot,
                    })
                except Exception as exc:
                    raise DeploymentControlError(f"could not persist Client progress snapshot: {exc}") from exc
                last_persisted[mac] = {**snapshot, "monotonic": now}
                self._last_persisted_progress = last_persisted
            self._progress[mac] = {**snapshot, "monotonic": now}

    def client_progress(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                mac: {key: value for key, value in item.items() if key != "monotonic"}
                for mac, item in self._progress.items()
            }

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
    ) -> ImageManifest:
        """Send an image set to one running restore Client."""
        tls_socket = self._running_session(mac_address, "restore")
        try:
            tls_socket.settimeout(86400)
            send_control_message(tls_socket, {
                "type": "transfer_offer", "job_id": self.coordinator.job.job_id,
                "image_id": self.coordinator.job.image_id,
            })
            def report_transfer_progress(completed: int, total: int) -> None:
                # This callback runs on the Server while it sends the image
                # payload. Persist it through the existing journal boundary;
                # never inject telemetry frames into the TLS artifact stream.
                self._record_client_progress(mac_address, {
                    "type": "progress",
                    "job_id": self.coordinator.job.job_id,
                    "phase": "transfer",
                    "completed_bytes": completed,
                    "total_bytes": total,
                })

            return send_image_set(
                tls_socket, repository, manifest_path,
                expected_image_id=self.coordinator.job.image_id,
                progress_callback=report_transfer_progress,
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
        on_received: Callable[[str], None] | None = None,
    ) -> str:
        """Receive an image set from one running save Client."""
        tls_socket = self._running_session(mac_address, "save")
        try:
            tls_socket.settimeout(86400)
            transfer = receive_control_message(tls_socket)
            while transfer.get("type") == "progress":
                self._record_client_progress(mac_address, transfer)
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
            expected_type = {"disk": "disk", "partition": "partition", "logical_volume": "logical_volume"}[self.coordinator.job.target_type]
            manifest_path = receive_image_set(
                tls_socket, repository,
                expected_image_id=self.coordinator.job.image_id,
                expected_image_type=expected_type,
            )
            if on_received is not None:
                try:
                    on_received(manifest_path)
                except Exception as exc:
                    raise DeploymentControlError(f"received image could not be committed to its destination repository: {exc}") from exc
            return manifest_path
        except (ImageTransferError, OSError, DeploymentControlError) as exc:
            self._record_transfer_failure(mac_address, f"saved image transfer failed: {exc}")
            if isinstance(exc, DeploymentControlError):
                raise
            raise DeploymentControlError(f"saved image transfer failed: {exc}") from exc

    def run_one_client_job(
        self,
        repository: str,
        *,
        manifest_path: str | None = None,
        result_timeout: float = 86400,
        saved_image_callback: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        """Arm and run one unicast save/restore job end to end."""
        if self.coordinator.job.transport != "unicast":
            raise DeploymentControlError("run_one_client_job only accepts unicast jobs")
        clients = self.coordinator.clients()
        if len(clients) != 1 or clients[0].state is not ClientState.READY:
            raise DeploymentControlError("initial unicast runtime requires exactly one selected READY Client")
        mac = clients[0].mac_address
        if self.coordinator.job.operation == "restore" and not manifest_path:
            raise DeploymentControlError("restore job requires an image manifest path")
        started = self.arm_and_start()
        if started != (mac,):
            return self.collect_results(timeout=result_timeout)
        try:
            if self.coordinator.job.operation == "restore":
                self.send_restore_image(
                    mac, repository, manifest_path,
                )
            else:
                self.receive_saved_image(
                    mac, repository, on_received=saved_image_callback,
                )
        except (DeploymentControlError, ImageTransferError):
            # The transfer method records a terminal failed result and closes
            # the session; collect_results returns that recorded state.
            pass
        return self.collect_results(timeout=result_timeout)

    def run_remote_clone_job(
        self,
        *,
        operation_log_path: str | None = None,
        result_timeout: float = 86400,
    ) -> dict[str, str]:
        """Clone one Server-local source to every READY Client over independent TLS sessions.

        Transfers are deliberately serialized on the Server so the source disk is
        read by only one sender at a time. Each Client retains its own local target
        approval and read-back verification; one failed receiver does not suppress
        attempts to the other already-authorized receivers.
        """
        job = self.coordinator.job
        if job.operation != "clone" or job.transport != "unicast":
            raise DeploymentControlError("remote clone requires a unicast clone job")
        clients = [
            item for item in self.coordinator.clients()
            if item.state is ClientState.READY
        ]
        if len(clients) < job.minimum_ready_clients:
            raise DeploymentControlError(
                f"remote clone requires at least {job.minimum_ready_clients} READY Client(s)"
            )
        if any(not job.authorizes_client(item.mac_address) for item in clients):
            raise DeploymentControlError("remote clone includes a Client outside the job allowlist")
        if not job.source_device:
            raise DeploymentControlError("clone job has no approved Server source device")

        transfers: dict[str, tuple[Any, Any]] = {}
        with self._lock:
            for record in clients:
                mac = record.mac_address
                target_device = self._target_devices.get(mac)
                tls_socket = self._sessions.get(mac)
                if not target_device or tls_socket is None:
                    raise DeploymentControlError(
                        f"Client {mac} clone target approval or control session is unavailable"
                    )
                header = build_remote_clone_header(
                    job.source_device, target_device, device_type=job.target_type,
                )
                transfers[mac] = (tls_socket, header)

        started = self.arm_and_start()
        if set(started) != set(transfers):
            for mac in started:
                self._record_transfer_failure(
                    mac, "remote clone start fan-out was incomplete; no Client received a data stream",
                )
            return self.collect_results(timeout=result_timeout)

        for mac in sorted(started):
            tls_socket, header = transfers[mac]
            try:
                def report_progress(completed: int, total: int, *, client_mac: str = mac) -> None:
                    now = time.monotonic()
                    with self._lock:
                        previous = self._progress.get(client_mac)
                        rate = 0.0
                        if (previous and previous.get("phase") == "clone"
                                and now > previous.get("monotonic", now)):
                            rate = max(
                                0.0,
                                (completed - previous["completed_bytes"])
                                / (now - previous["monotonic"]),
                            )
                        self._progress[client_mac] = {
                            "phase": "clone", "completed_bytes": completed,
                            "total_bytes": total, "bytes_per_second": round(rate, 1),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "monotonic": now,
                        }

                kwargs: dict[str, Any] = {
                    "source_path": job.source_device,
                    "confirmation": f"READ {job.source_device}",
                    "progress_callback": report_progress,
                }
                if operation_log_path is not None:
                    kwargs["operation_log_path"] = operation_log_path
                send_remote_disk(tls_socket, header, **kwargs)
            except Exception as exc:
                self._record_transfer_failure(
                    mac, f"remote {job.target_type} clone failed: {exc}",
                )
            finally:
                with self._lock:
                    current = self._progress.get(mac)
                    if current is not None:
                        current.pop("monotonic", None)
        return self.collect_results(timeout=result_timeout)

    def run_physical_multicast_clone_job(
        self,
        *,
        udpcast_config: UDPcastConfig,
        result_timeout: float = 86400,
    ) -> dict[str, str]:
        """Clone one read-only Server disk directly to all approved Client disks."""
        from feclora.network.physical_multicast import (
            PhysicalMulticastError, build_physical_device_record,
            open_approved_block_device, validate_physical_multicast_cohort,
        )
        from feclora.network.udpcast import send_physical_multicast_stream
        from feclora.storage.inventory import collect_inventory

        job = self.coordinator.job
        if job.operation != "clone" or job.transport != "multicast" or job.target_type != "disk":
            raise DeploymentControlError("physical multicast requires a whole-disk multicast clone job")
        if (udpcast_config.interface != job.network_interface
                or udpcast_config.data_group != job.multicast_group
                or udpcast_config.portbase != job.multicast_port
                or udpcast_config.min_receivers != len(job.authorized_clients)):
            raise DeploymentControlError("physical UDPcast configuration does not match the selected Client cohort")

        def find_source() -> dict[str, Any]:
            inventory = collect_inventory()
            matches: list[dict[str, Any]] = []
            def visit(items: list[dict[str, Any]]) -> None:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("path") == job.source_device and item.get("type") == "disk":
                        matches.append(item)
                    visit(item.get("children", []))
            visit(inventory.get("devices", []))
            if len(matches) != 1:
                raise DeploymentControlError("Server source must resolve to exactly one whole disk")
            return matches[0]

        source_fd = None
        try:
            if not job.source_identity_json:
                raise PhysicalMulticastError("Server source identity was not bound when the job was created")
            source_approved = json.loads(job.source_identity_json)
            source_current = build_physical_device_record(find_source())
            with self._lock:
                approved_destinations = {
                    mac: dict(self._target_identities[mac])
                    for mac in job.authorized_clients if mac in self._target_identities
                }
                sessions = {mac: self._sessions.get(mac) for mac in job.authorized_clients}
            states = {item.mac_address: item.state.value for item in self.coordinator.clients()}
            validate_physical_multicast_cohort(
                source_approved, source_current, job.authorized_clients, states,
                approved_destinations, dict(approved_destinations),
            )
            if any(sessions.get(mac) is None for mac in job.authorized_clients):
                raise PhysicalMulticastError("a selected Client has no live control session")
            source_fd = open_approved_block_device(
                source_approved, source_current, role="Server source",
            )
            expected_bytes = source_approved["size_bytes"]
            digest = hashlib.sha256()
            offset = 0
            while offset < expected_bytes:
                chunk = os.pread(source_fd, min(1024 * 1024, expected_bytes - offset), offset)
                if not chunk:
                    raise PhysicalMulticastError("Server source ended during pre-transfer SHA-256 scan")
                digest.update(chunk)
                offset += len(chunk)
            stream_metadata = {"expected_bytes": expected_bytes, "sha256": digest.hexdigest()}
            started = self.arm_and_start(physical_stream=stream_metadata)
            if set(started) != set(job.authorized_clients):
                raise DeploymentControlError("not every selected Client accepted physical multicast START")
            # Every Client must revalidate and exclusively open its disk before
            # the first multicast byte is emitted.
            for mac in sorted(job.authorized_clients):
                response = receive_control_message(sessions[mac], expected_type="physical_ready")
                if (set(response) != {"type", "job_id", "ready", "detail"}
                        or response.get("job_id") != job.job_id
                        or not isinstance(response.get("ready"), bool)
                        or not isinstance(response.get("detail"), str)):
                    raise DeploymentControlError(f"Client {mac} returned an invalid physical-ready acknowledgement")
                if response["ready"] is not True:
                    raise DeploymentControlError(
                        f"Client {mac} could not prepare its destination; no data was sent: {response['detail'][:256]}"
                    )
            with os.fdopen(os.dup(source_fd), "rb", buffering=0) as source_stream:
                sent = send_physical_multicast_stream(
                    source_stream, expected_bytes=expected_bytes,
                    config=udpcast_config, firewall=self.firewall,
                )
            if sent.get("sha256") != stream_metadata["sha256"]:
                raise DeploymentControlError("Server source changed between hash scan and multicast send")
            return self.collect_results(timeout=result_timeout)
        except (PhysicalMulticastError, OSError, UDPcastError, DeploymentControlError) as exc:
            raise DeploymentControlError(f"physical multicast clone failed: {exc}") from exc
        finally:
            if source_fd is not None:
                os.close(source_fd)

    def run_multicast_restore_job(
        self,
        repository: str,
        manifest_path: str,
        *,
        udpcast_config: UDPcastConfig,
        result_timeout: float = 86400,
    ) -> dict[str, str]:
        """Restore one image to READY Clients over UDPcast."""
        job = self.coordinator.job
        if job.transport != "multicast" or job.operation != "restore":
            raise DeploymentControlError("multicast runtime supports restore jobs only")
        if (udpcast_config.interface != job.network_interface
                or udpcast_config.data_group != job.multicast_group
                or udpcast_config.portbase != job.multicast_port):
            raise DeploymentControlError("UDPcast configuration does not match the job")
        clients = [
            item for item in self.coordinator.clients()
            if item.state is ClientState.READY
        ]
        if len(clients) < job.minimum_ready_clients:
            raise DeploymentControlError(
                f"multicast restore requires at least {job.minimum_ready_clients} READY Client(s)"
            )
        if any(not job.authorizes_client(item.mac_address) for item in clients):
            raise DeploymentControlError("multicast restore includes a Client outside the job allowlist")
        if udpcast_config.min_receivers != job.minimum_ready_clients:
            raise DeploymentControlError("UDPcast receiver threshold must match the deployment start policy")
        try:
            with open(manifest_path, "rb") as stream:
                manifest_bytes = stream.read(8 * 1024 + 1)
            if len(manifest_bytes) > 8 * 1024:
                raise DeploymentControlError("manifest exceeds the multicast control-plane size limit")
            manifest = ImageManifest.from_json(manifest_bytes.decode("utf-8"))
            if manifest.image_id != job.image_id:
                raise DeploymentControlError("manifest image identifier does not match the multicast job")
            if manifest.image_type != job.target_type:
                raise DeploymentControlError("manifest image type does not match the multicast job target type")
            if not manifest.artifacts:
                raise DeploymentControlError("multicast image manifest contains no artifacts")
            for artifact in manifest.artifacts:
                verify_artifact_file(os.path.join(repository, artifact.filename), artifact)
        except (OSError, UnicodeError, ManifestValidationError, UDPcastError) as exc:
            raise DeploymentControlError(f"cannot verify multicast image manifest: {exc}") from exc
        expected_macs = tuple(sorted(item.mac_address for item in clients))
        started = self.arm_and_start()
        if tuple(sorted(started)) != expected_macs:
            raise DeploymentControlError("not every selected Client accepted the multicast START")
        offer = {
            "type": "transfer_offer",
            "job_id": job.job_id,
            "image_id": job.image_id,
            "manifest_b64": base64.b64encode(manifest_bytes).decode("ascii"),
        }
        with self._lock:
            sessions = tuple((mac, self._sessions.get(mac)) for mac in expected_macs)
        try:
            for mac, tls_socket in sessions:
                if tls_socket is None:
                    raise DeploymentControlError(f"Client {mac} lost its control session")
                send_control_message(tls_socket, offer)
            for artifact in manifest.artifacts:
                source_path = os.path.join(repository, artifact.filename)
                send_multicast_artifact(
                    self.coordinator, source_path, manifest_path,
                    udpcast_config, firewall=self.firewall,
                )
        except (OSError, DeploymentControlError, UDPcastError, PXEFirewallError) as exc:
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
                message = receive_control_message(tls_socket)
                while message.get("type") == "progress":
                    self._record_client_progress(mac, message)
                    message = receive_control_message(tls_socket)
                if message.get("type") != "result":
                    raise DeploymentControlError("client did not send a terminal result")
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
    expected_server_identity: str,
    mac_address: str,
    job_id: str,
    timeout: float = 15,
    source_address: str | None = None,
    network_interface: str | None = None,
) -> DeploymentJob:
    """Read a job offer over TLS that authenticates only the Server certificate."""
    if not isinstance(mac_address, str) or not mac_address or len(mac_address) > 32:
        raise DeploymentControlError("client MAC address is required")
    if not isinstance(job_id, str) or not job_id or len(job_id) > 64:
        raise DeploymentControlError("deployment job UUID is required")
    tls_socket = connect_tls(
        tls_context, host, port, expected_peer_identity=expected_server_identity,
        timeout=timeout, io_timeout=timeout, source_address=source_address,
        network_interface=network_interface,
    )
    with tls_socket:
        send_control_message(tls_socket, {
            "type": "inspect", "job_id": job_id, "mac_address": mac_address.lower(),
        })
        offer = receive_control_message(tls_socket, expected_type="job")
        if set(offer) != {"type", "job", "server_identity"}:
            raise DeploymentControlError("server job offer contains missing or unknown fields")
        if offer["server_identity"] != expected_server_identity:
            raise DeploymentControlError("job offer is not bound to the verified Server identity")
        try:
            job = DeploymentJob.from_dict(offer["job"])
        except (JobValidationError, TypeError) as exc:
            raise DeploymentControlError(f"server supplied an invalid deployment job: {exc}") from exc
        if job.job_id != job_id or not job.authorizes_client(mac_address):
            raise DeploymentControlError("job does not authorize this Client MAC")
        if job.transport == "multicast" and job.operation not in {"restore", "clone"}:
            raise DeploymentControlError("multicast Client jobs support restore or physical clone only")
        return job


def join_deployment(
    host: str,
    port: int,
    tls_context: ssl.SSLContext,
    *,
    expected_server_identity: str,
    mac_address: str,
    job_id: str,
    prepare_local_target: Callable[[DeploymentJob], LocalTargetApproval],
    execute_job: Callable[[DeploymentJob, Any, LocalTargetApproval], tuple[bool, str]],
    timeout: float = 120,
    source_address: str | None = None,
    network_interface: str | None = None,
) -> tuple[DeploymentJob, bool, str]:
    """Connect without client authentication, obtain local target approval, then execute on START."""
    if not isinstance(mac_address, str) or not mac_address or len(mac_address) > 32:
        raise DeploymentControlError("client MAC address is required")
    if not isinstance(job_id, str) or not job_id or len(job_id) > 64:
        raise DeploymentControlError("deployment job UUID is required")
    tls_socket = connect_tls(
        tls_context, host, port, expected_peer_identity=expected_server_identity,
        timeout=15, io_timeout=timeout, source_address=source_address,
        network_interface=network_interface,
    )
    with tls_socket:
        send_control_message(tls_socket, {
            "type": "hello", "job_id": job_id, "mac_address": mac_address.lower(),
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
        if job.transport == "multicast" and job.operation not in {"restore", "clone"}:
            raise DeploymentControlError("multicast Client jobs support restore or physical clone only")
        if job.job_id != job_id or not job.authorizes_client(mac_address):
            raise DeploymentControlError("job does not authorize this Client MAC")
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
            f"ERASE {device_path}"
            if job.operation in {"restore", "clone"}
            else f"READ {device_path}"
        )
        if approval.confirmation != required_confirmation:
            raise DeploymentControlError("local typed target confirmation does not match the selected device")
        ready_message = {
            "type": "ready", "job_id": job.job_id,
            "target_description": description, "locally_authorized": True,
        }
        if job.operation == "clone":
            ready_message["target_device"] = device_path
            if job.transport == "multicast":
                if not isinstance(approval.physical_identity, Mapping):
                    raise DeploymentControlError("physical multicast requires an independently inventoried local destination identity")
                if approval.physical_identity.get("path") != device_path:
                    raise DeploymentControlError("physical destination identity does not match the approved target path")
                ready_message["target_identity"] = dict(approval.physical_identity)
        send_control_message(tls_socket, ready_message)
        start = receive_control_message(tls_socket)
        if start.get("type") == "cancel":
            if set(start) != {"type", "job_id"} or start.get("job_id") != job.job_id:
                raise DeploymentControlError("server cancellation is not bound to this job")
            raise DeploymentControlError("server cancelled the deployment before start")
        expected_start_fields = {"type", "job_id", "operation", "image_id"}
        if job.operation == "clone" and job.transport == "multicast":
            expected_start_fields.add("physical_stream")
        if set(start) != expected_start_fields:
            raise DeploymentControlError("server start command contains missing or unknown fields")
        if start.get("type") != "start" or start.get("job_id") != job.job_id:
            raise DeploymentControlError("server did not arm this deployment job")
        if start.get("operation") != job.operation or start.get("image_id") != job.image_id:
            raise DeploymentControlError("server start command does not match the active job")
        if job.operation == "clone" and job.transport == "multicast":
            physical_stream = start.get("physical_stream")
            if (not isinstance(physical_stream, dict)
                    or set(physical_stream) != {"expected_bytes", "sha256"}
                    or isinstance(physical_stream.get("expected_bytes"), bool)
                    or not isinstance(physical_stream.get("expected_bytes"), int)
                    or physical_stream["expected_bytes"] <= 0
                    or not isinstance(physical_stream.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", physical_stream["sha256"])):
                raise DeploymentControlError("Server physical stream metadata is invalid")
            approval = LocalTargetApproval(
                approval.device_path, approval.description, approval.confirmation,
                approval.physical_identity, physical_stream,
            )
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
