"""Persistent, single-job Server deployment service for Cockpit.

The service reuses the established TLS control plane, coordinator, journal and
image-transfer engines. It never resumes an interrupted job after process loss.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import signal
import socket
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from feclora.deployment.control import DeploymentControlError, DeploymentControlServer
from feclora.deployment.coordinator import ClientState, CoordinatorError, DeploymentCoordinator, JobState
from feclora.deployment.job import DeploymentJob
from feclora.deployment.journal import DeploymentJournal
from feclora.deployment.local_control import LocalControlError, LocalControlServer
from feclora.deployment.multicast_runtime import udpcast_config_for_job
from feclora.deployment.runtime_config import load_server_runtime_config
from feclora.network.firewall import PXEFirewall
from feclora.network.multicast_preflight import inspect_multicast_interface
from feclora.network.remote_clone_protocol import create_mutual_tls_context
from feclora.network.pxe_service import PXEServiceManager
from feclora.storage.image_security import verify_manifest_signature


RUNTIME_DIRECTORY = Path("/run/feclora")
IPC_SOCKET = RUNTIME_DIRECTORY / "deployment.sock"
LOCK_FILE = RUNTIME_DIRECTORY / "deployment.lock"
JOURNAL_DIRECTORY = Path("/var/lib/feclora/deployments")
CONFIG_FILE = "/etc/feclora/deployment-server.json"


class DeploymentServiceError(RuntimeError):
    """Persistent deployment service could not start or execute safely."""


class DeploymentService:
    def __init__(self, job_id: str) -> None:
        try:
            canonical = str(UUID(job_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise DeploymentServiceError("job ID must be a canonical UUID") from exc
        if canonical != job_id:
            raise DeploymentServiceError("job ID must be a canonical lowercase UUID")
        self.job_id = canonical
        self.config = load_server_runtime_config(CONFIG_FILE)
        self.journal_path = JOURNAL_DIRECTORY / (canonical + ".jsonl")
        self.journal = DeploymentJournal.inspect(self.journal_path)
        report = self.journal.recovery_report()
        if report["job_id"] != canonical:
            raise DeploymentServiceError("journal identity does not match requested job")
        if report["job_state"] != "created" or report["interrupted"]:
            raise DeploymentServiceError(
                "job is not a fresh, unstarted definition; inspect and reconcile its journal instead of resuming it"
            )
        if report["clients"]:
            raise DeploymentServiceError(
                "journal already contains Client session history; this service will not recreate or resume sessions"
            )
        self.job = DeploymentJob.from_dict(report["job"])
        if self.job.network_interface not in {name for _index, name in socket.if_nameindex()}:
            raise DeploymentServiceError("job network interface is no longer present")
        from feclora.network.interface_discovery import discover_interface_addresses
        try:
            interface_addresses = discover_interface_addresses(self.job.network_interface)
        except Exception as exc:
            raise DeploymentServiceError(f"cannot validate the job's Server interface: {exc}") from exc
        if self.config.bind_address not in {item.address for item in interface_addresses}:
            raise DeploymentServiceError("configured Server bind address is not assigned to the job interface")
        if self.job.start_policy != "manual":
            raise DeploymentServiceError("persistent Cockpit deployment service accepts manual start policy only")
        if self.job.transport == "unicast" and len(self.job.authorized_clients) != 1:
            raise DeploymentServiceError("persistent unicast service requires exactly one authorized Client")
        if self.job.transport == "multicast" and (
            self.job.operation != "restore" or len(self.job.authorized_clients) < 2
        ):
            raise DeploymentServiceError("persistent multicast service requires a multi-Client restore job")
        if self.job.operation == "restore":
            self.manifest_path = str(Path(self.config.repository) / (self.job.image_id + ".manifest.json"))
            verify_manifest_signature(self.manifest_path, self.config.server_minisign_public_key)
        else:
            self.manifest_path = None

        self.coordinator = DeploymentCoordinator.from_journal(self.job, self.journal)
        self.firewall = PXEFirewall()
        # If PXE already owns this interface's temporary zone, adopt it so the
        # deployment listener adds/removes only its own TCP port.
        pxe_manager = PXEServiceManager(firewall=self.firewall)
        pxe_state = pxe_manager._read_state()
        if pxe_state is not None and pxe_state["interface"] == self.job.network_interface:
            self.firewall.adopt(self.job.network_interface, pxe_state["firewall"])
        context = create_mutual_tls_context(
            "server", ca_file=self.config.ca_file,
            certificate_file=self.config.certificate_file,
            private_key_file=self.config.private_key_file,
        )
        self.control = DeploymentControlServer(
            self.coordinator, context,
            local_identity=self.config.local_identity,
            client_identity_to_mac=self.config.client_identity_to_mac,
            firewall=self.firewall,
            interface=self.job.network_interface,
        )
        self.ipc = LocalControlServer(str(IPC_SOCKET), self._handle_ipc, allowed_uid=0)
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.RLock()
        self._arm_requested = False
        self._last_error: str | None = None
        self._stop_event = threading.Event()
        self._lock_fd: int | None = None

    def _acquire_instance_lock(self) -> None:
        info = os.lstat(RUNTIME_DIRECTORY)
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o022):
            raise DeploymentServiceError("service runtime directory must be root-owned and not group/other-writable")
        fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            os.close(fd)
            raise DeploymentServiceError("deployment service lock file is unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise DeploymentServiceError("another Feclora deployment service instance is already active") from exc
        self._lock_fd = fd

    def _status(self) -> dict[str, Any]:
        clients = self.coordinator.clients()
        result: dict[str, Any] = {
            "job_id": self.job.job_id,
            "job_state": self.coordinator.state.value,
            "operation": self.job.operation,
            "image_id": self.job.image_id,
            "transport": self.job.transport,
            "clients": [
                {"mac_address": item.mac_address, "state": item.state.value, "detail": item.detail}
                for item in clients
            ],
            "authorized_clients": list(self.job.authorized_clients),
            "listener_address": self.control.bound_address,
            "listener_errors": self.control.listener_errors[-5:],
            "worker_active": bool(self._worker and self._worker.is_alive()),
            "last_error": self._last_error,
            "automatic_resume": False,
        }
        if self.job.transport == "multicast":
            try:
                preflight = inspect_multicast_interface(
                    self.job.network_interface, self.job.multicast_group, role="sender",
                )
                result["multicast_preflight"] = {
                    "interface": preflight.interface,
                    "ipv4_address": preflight.ipv4_address,
                    "route_interface": preflight.route_interface,
                    "warnings": list(preflight.warnings),
                }
            except Exception as exc:
                result["multicast_preflight"] = {"error": str(exc)}
        return result

    def _handle_ipc(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "status":
            return self._status()
        if set(params) != {"job_id", "confirmation"}:
            raise DeploymentServiceError("mutating command requires job_id and confirmation")
        if params["job_id"] != self.job.job_id:
            raise DeploymentServiceError("command job UUID does not match the active job")
        confirmation = params["confirmation"]
        if not isinstance(confirmation, str) or len(confirmation) > 96:
            raise DeploymentServiceError("operator confirmation is invalid")
        if action == "arm":
            required = (
                "ARM MULTICAST " + self.job.job_id
                if self.job.transport == "multicast"
                else "ARM " + self.job.job_id
            )
            if confirmation != required:
                raise DeploymentServiceError("arm confirmation does not match the exact job-specific phrase")
            if self.job.transport == "multicast":
                preflight = inspect_multicast_interface(
                    self.job.network_interface, self.job.multicast_group, role="sender",
                )
                if preflight.route_interface != self.job.network_interface:
                    raise DeploymentServiceError("multicast route does not use the selected deployment interface")
            with self._worker_lock:
                if self._arm_requested or self.coordinator.state is not JobState.CREATED:
                    raise DeploymentServiceError("job is already armed, running or terminal")
                clients = self.coordinator.clients()
                if len(clients) != len(self.job.authorized_clients) or any(
                    client.state is not ClientState.READY for client in clients
                ):
                    raise DeploymentServiceError("every authorized Client must be connected and READY before arming")
                self._arm_requested = True
                self._worker = threading.Thread(
                    target=self._run_job, name="feclora-deployment-job", daemon=True,
                )
                self._worker.start()
            return {"job_id": self.job.job_id, "accepted": True,
                    "message": "Explicit arm accepted; the existing deployment engine is executing in the service."}
        if action == "cancel":
            if confirmation != "CANCEL " + self.job.job_id:
                raise DeploymentServiceError("cancel confirmation must match the exact job UUID")
            with self._worker_lock:
                if self._arm_requested or self.coordinator.state is not JobState.CREATED:
                    raise DeploymentServiceError(
                        "safe cancellation is available only before arming; active disk I/O is never interrupted"
                    )
                self.control.cancel()
            return {"job_id": self.job.job_id, "job_state": self.coordinator.state.value,
                    "message": "Unarmed job cancelled; no storage operation was started."}
        raise DeploymentServiceError("unsupported deployment service action")

    def _run_job(self) -> None:
        try:
            if self.job.transport == "multicast":
                udpcast = udpcast_config_for_job(
                    self.job, min_receivers=len(self.job.authorized_clients),
                )
                self.control.run_multicast_restore_job(
                    self.config.repository, self.manifest_path,
                    trusted_public_key=self.config.server_minisign_public_key,
                    udpcast_config=udpcast,
                )
            else:
                mac = self.job.authorized_clients[0]
                trusted_key = (
                    self.config.server_minisign_public_key
                    if self.job.operation == "restore"
                    else self.config.client_minisign_public_keys[mac]
                )
                self.control.run_one_client_job(
                    self.config.repository,
                    trusted_public_key=trusted_key,
                    manifest_path=self.manifest_path,
                )
        except Exception as exc:
            self._last_error = str(exc)[:512]
            # Do not retry or reconstruct a live session. The journal remains
            # authoritative; interrupted states require operator inspection.
        finally:
            with self._worker_lock:
                if self.coordinator.state is JobState.CREATED:
                    self._arm_requested = False

    def run(self) -> None:
        self._acquire_instance_lock()
        service_start_recorded = False
        try:
            self.journal({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": self.job.job_id,
                "event": "service_started",
                "job_state": self.coordinator.state.value,
                "detail": "Persistent Server control service started; no storage operation armed.",
            })
            service_start_recorded = True
            self.control.start(self.config.bind_address, self.config.port)
            self.ipc.start()
            while not self._stop_event.wait(0.5):
                pass
        finally:
            try:
                self.ipc.stop()
            finally:
                try:
                    self.control.stop()
                    if (service_start_recorded and self.coordinator.state is JobState.CREATED
                            and not self.coordinator.clients()):
                        self.journal({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "job_id": self.job.job_id,
                            "event": "service_stopped",
                            "job_state": JobState.CREATED.value,
                            "detail": "Service stopped cleanly before any Client session or storage operation.",
                        })
                finally:
                    if self._lock_fd is not None:
                        os.close(self._lock_fd)
                        self._lock_fd = None

    def stop(self) -> None:
        self._stop_event.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feclora persistent deployment Server service")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    service = None
    try:
        service = DeploymentService(args.job_id)
        signal.signal(signal.SIGTERM, lambda _signum, _frame: service.stop())
        signal.signal(signal.SIGINT, lambda _signum, _frame: service.stop())
        service.run()
        return 0
    except Exception as exc:
        print(f"feclora deployment service: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
