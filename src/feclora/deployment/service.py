"""Persistent, single-job Server deployment service for Cockpit.

The service reuses the established TLS control plane, coordinator, journal and
image-transfer engines. It never resumes an interrupted job after process loss.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import socket
import stat
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from feclora.deployment.control import DeploymentControlServer
from feclora.deployment.coordinator import ClientState, DeploymentCoordinator, JobState
from feclora.deployment.job import DeploymentJob
from feclora.deployment.journal import DeploymentJournal
from feclora.deployment.local_control import LocalControlServer
from feclora.deployment.multicast_runtime import udpcast_config_for_job
from feclora.deployment.runtime_config import load_server_runtime_config
from feclora.network.firewall import PXEFirewall
from feclora.network.multicast_preflight import inspect_multicast_interface
from feclora.network.remote_clone_protocol import create_tls_context
from feclora.network.pxe_service import PXEServiceManager
from feclora.storage.image_security import verify_manifest_signature


RUNTIME_DIRECTORY = Path("/run/feclora")
IPC_SOCKET = RUNTIME_DIRECTORY / "deployment.sock"
LOCK_FILE = RUNTIME_DIRECTORY / "deployment.lock"
FIREWALL_STATE = RUNTIME_DIRECTORY / "deployment-firewall.json"
JOURNAL_DIRECTORY = Path("/var/lib/feclora/deployments")
CONFIG_FILE = "/etc/feclora/deployment-server.json"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate firewall state field")
        result[key] = value
    return result


def _acquire_recovery_lock() -> int:
    runtime_info = os.lstat(RUNTIME_DIRECTORY)
    if (not stat.S_ISDIR(runtime_info.st_mode) or stat.S_ISLNK(runtime_info.st_mode)
            or runtime_info.st_uid != 0 or runtime_info.st_mode & 0o022):
        raise DeploymentServiceError("runtime directory is unsafe during recovery")
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        os.close(fd)
        raise DeploymentServiceError("deployment service lock file is unsafe during recovery")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise DeploymentServiceError("another deployment service is active; refusing runtime recovery") from exc
    return fd


def recover_stale_firewall_state(*, lock_held: bool = False) -> None:
    """Restore deployment-owned temporary firewalld rules after a crash."""
    try:
        initial = os.lstat(FIREWALL_STATE)
    except FileNotFoundError:
        return
    if (not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode)
            or initial.st_uid != 0 or initial.st_mode & 0o077 or initial.st_size > 8192):
        raise DeploymentServiceError("stale deployment firewall state is unsafe")
    lock_fd = None
    try:
        if not lock_held:
            lock_fd = _acquire_recovery_lock()
        fd = os.open(FIREWALL_STATE, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                    or info.st_mode & 0o077 or info.st_size > 8192
                    or (info.st_dev, info.st_ino) != (initial.st_dev, initial.st_ino)):
                raise DeploymentServiceError("stale deployment firewall state changed during inspection")
            raw = os.read(fd, 8193)
        finally:
            os.close(fd)
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise DeploymentServiceError("stale deployment firewall state is unreadable") from exc
        if (not isinstance(value, dict)
                or set(value) != {"schema_version", "interface", "firewall", "opened_by_service", "added_ports", "added_protocols"}
                or value["schema_version"] != 1 or isinstance(value["schema_version"], bool)
                or not isinstance(value["interface"], str)
                or not isinstance(value["opened_by_service"], bool)
                or not isinstance(value["added_ports"], list)
                or any(
                    not isinstance(port, str)
                    or not re.fullmatch(r"(?:[1-9][0-9]{0,4})/(?:tcp|udp)", port)
                    or int(port.split("/", 1)[0]) > 65535
                    for port in value["added_ports"]
                )
                or not isinstance(value["added_protocols"], list)
                or any(not isinstance(protocol, str) or not re.fullmatch(r"[a-z0-9-]{1,32}", protocol)
                       for protocol in value["added_protocols"])):
            raise DeploymentServiceError("stale deployment firewall state has an invalid schema")
        recovery = PXEFirewall()
        try:
            recovery.adopt(value["interface"], value["firewall"])
            if value["opened_by_service"]:
                if value["added_ports"] or value["added_protocols"]:
                    raise DeploymentServiceError("owned firewall zone cannot also declare separately added rules")
                recovery.close(value["interface"])
            else:
                zone = value["firewall"]["zone"]
                current_ports = recovery._call([f"--zone={zone}", "--list-ports"], check=False)
                current_protocols = recovery._call([f"--zone={zone}", "--list-protocols"], check=False)
                if current_ports.returncode != 0 or current_protocols.returncode != 0:
                    raise DeploymentServiceError("cannot inspect current firewall rules for crash recovery")
                present_ports = set(current_ports.stdout.split())
                present_protocols = set(current_protocols.stdout.split())
                recovery.remove_ports(
                    value["interface"],
                    [port for port in value["added_ports"] if port in present_ports],
                )
                recovery.remove_protocols(
                    value["interface"],
                    [protocol for protocol in value["added_protocols"] if protocol in present_protocols],
                )
        except Exception as exc:
            raise DeploymentServiceError(f"cannot safely restore stale deployment firewall state: {exc}") from exc
        current = os.lstat(FIREWALL_STATE)
        if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
            raise DeploymentServiceError("stale deployment firewall state changed before cleanup")
        FIREWALL_STATE.unlink()
        directory_fd = os.open(RUNTIME_DIRECTORY, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def recover_stale_ipc_socket(*, lock_held: bool = False) -> None:
    """Remove only a stale root-owned Feclora Unix socket after its service lock is free."""
    try:
        initial = os.lstat(IPC_SOCKET)
    except FileNotFoundError:
        return
    if (not stat.S_ISSOCK(initial.st_mode) or initial.st_uid != 0
            or initial.st_mode & 0o077):
        raise DeploymentServiceError("stale deployment IPC path is not a private root-owned Unix socket")
    lock_fd = None
    try:
        if not lock_held:
            lock_fd = _acquire_recovery_lock()
        current = os.lstat(IPC_SOCKET)
        if (not stat.S_ISSOCK(current.st_mode) or current.st_uid != 0
                or (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino)):
            raise DeploymentServiceError("deployment IPC socket changed during stale-path inspection")
        IPC_SOCKET.unlink()
        directory_fd = os.open(RUNTIME_DIRECTORY, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def recover_stale_runtime_artifacts(*, lock_held: bool = False) -> None:
    """Recover stale firewall and IPC artifacts while holding single-job ownership."""
    lock_fd = None
    try:
        if not lock_held:
            lock_fd = _acquire_recovery_lock()
        recover_stale_firewall_state(lock_held=True)
        recover_stale_ipc_socket(lock_held=True)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)



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
        if self.job.operation == "save" and self.job.target_type != "disk":
            raise DeploymentServiceError("persistent Client capture supports whole-disk jobs only")
        if self.job.transport == "unicast" and len(self.job.authorized_clients) != 1:
            raise DeploymentServiceError("persistent unicast service requires exactly one authorized Client")
        if self.job.transport == "multicast" and (
            self.job.operation != "restore" or len(self.job.authorized_clients) < 2
        ):
            raise DeploymentServiceError("persistent multicast service requires a multi-Client restore job")
        if self.job.transport == "multicast":
            try:
                inspect_multicast_interface(
                    self.job.network_interface, self.job.multicast_group, role="sender",
                )
            except Exception as exc:
                raise DeploymentServiceError(f"multicast Server interface preflight failed: {exc}") from exc
        self.repository_path = self.config.repository
        if self.job.operation == "restore":
            if self.job.repository_id is not None:
                from feclora.storage.repository_manager import RemoteRepositoryManager
                try:
                    self.repository_path = RemoteRepositoryManager().resolve(
                        self.job.repository_id, write=False,
                    )
                except Exception as exc:
                    raise DeploymentServiceError(
                        f"selected image repository is not mounted and verified: {exc}"
                    ) from exc
            self.manifest_path = str(Path(self.repository_path) / (self.job.image_id + ".manifest.json"))
            signature_path = self.manifest_path + ".minisig"
            if os.path.lexists(signature_path):
                if not self.config.server_minisign_public_key:
                    raise DeploymentServiceError("selected image is signed but no independently trusted Server minisign key is configured")
                verify_manifest_signature(self.manifest_path, self.config.server_minisign_public_key)
        else:
            self.manifest_path = None

        self.coordinator = DeploymentCoordinator.from_journal(self.job, self.journal)
        self.firewall = PXEFirewall()
        # If PXE already owns this interface's temporary zone, adopt it so the
        # deployment listener adds/removes only its own TCP port.
        pxe_manager = PXEServiceManager(firewall=self.firewall)
        self._pxe_state = pxe_manager._read_state()
        if self._pxe_state is not None and self._pxe_state["interface"] == self.job.network_interface:
            self._base_firewall_ports = set(self._pxe_state["firewall"]["ports"])
            self._base_firewall_protocols = set(self._pxe_state["firewall"].get("protocols", []))
        else:
            self._base_firewall_ports = set()
            self._base_firewall_protocols = set()
        context = create_tls_context(
            "server", ca_file=self.config.ca_file,
            certificate_file=self.config.certificate_file,
            private_key_file=self.config.private_key_file,
        )
        self.control = DeploymentControlServer(
            self.coordinator, context,
            local_identity=self.config.local_identity,
            firewall=self.firewall,
            interface=self.job.network_interface,
            progress_event_sink=self.journal,
        )
        self.ipc = LocalControlServer(str(IPC_SOCKET), self._handle_ipc, allowed_uid=0)
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.RLock()
        self._arm_requested = False
        self._last_error: str | None = None
        self._stop_event = threading.Event()
        self._lock_fd: int | None = None

    def _firewall_changed(self, interface: str) -> None:
        if not self.firewall.is_open(interface):
            self._write_firewall_state(None)
            return
        state = self.firewall.export_state(interface)
        opened_by_service = (
            self._pxe_state is None or self._pxe_state["interface"] != interface
        )
        added_ports = [] if opened_by_service else sorted(
            set(state["ports"]) - self._base_firewall_ports
        )
        added_protocols = [] if opened_by_service else sorted(
            set(state.get("protocols", [])) - self._base_firewall_protocols
        )
        self._write_firewall_state({
            "interface": interface,
            "firewall": state,
            "opened_by_service": opened_by_service,
            "added_ports": added_ports,
            "added_protocols": added_protocols,
        })

    def _write_firewall_state(self, value: dict[str, Any] | None) -> None:
        if value is None:
            try:
                info = os.lstat(FIREWALL_STATE)
                if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
                    raise DeploymentServiceError("deployment firewall state path is unsafe")
                FIREWALL_STATE.unlink()
            except FileNotFoundError:
                pass
            return
        record = {"schema_version": 1, "added_protocols": [], **value}
        fd, temporary = tempfile.mkstemp(prefix=".deployment-firewall.", dir=RUNTIME_DIRECTORY)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, FIREWALL_STATE)
            directory_fd = os.open(RUNTIME_DIRECTORY, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

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
        # Progress is a snapshot shared by all clients; collect it once so a
        # large deployment reports one coherent view without repeated work.
        progress_by_client = self.control.client_progress()
        result: dict[str, Any] = {
            "job_id": self.job.job_id,
            "job_state": self.coordinator.state.value,
            "operation": self.job.operation,
            "image_id": self.job.image_id,
            "transport": self.job.transport,
            "network_interface": self.job.network_interface,
            "clients": [
                {
                    "mac_address": item.mac_address, "state": item.state.value,
                    "progress": progress_by_client.get(item.mac_address),
                }
                for item in clients[:128]
            ],
            "client_count": len(clients),
            "clients_truncated": len(clients) > 128,
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
        if not isinstance(confirmation, str) or len(confirmation) > 512:
            raise DeploymentServiceError("operator confirmation is invalid")
        if action == "arm":
            if self.job.operation == "clone":
                if not self.job.source_device:
                    raise DeploymentServiceError("clone source device is unavailable")
                required = f"ARM {self.job.job_id} AND READ {self.job.source_device}"
            else:
                required = (
                    "ARM MULTICAST " + self.job.job_id + " IGMP-VERIFIED"
                    if self.job.transport == "multicast"
                    else "ARM " + self.job.job_id
                )
            if confirmation != required:
                raise DeploymentServiceError("arm confirmation does not match the exact job-specific phrase")
            if self.job.transport == "multicast":
                try:
                    preflight = inspect_multicast_interface(
                        self.job.network_interface, self.job.multicast_group, role="sender",
                    )
                except Exception as exc:
                    raise DeploymentServiceError(f"multicast Server interface preflight failed: {exc}") from exc
                if preflight.route_interface != self.job.network_interface:
                    raise DeploymentServiceError("multicast route does not use the selected deployment interface")
            with self._worker_lock:
                if self._stop_event.is_set():
                    raise DeploymentServiceError("service shutdown has begun; refusing to arm a new storage operation")
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
        self._last_error = None
        try:
            if self.job.operation == "clone":
                self.control.run_remote_clone_job(
                    operation_log_path="/var/lib/feclora/operations.jsonl",
                )
            elif self.job.transport == "multicast":
                udpcast = udpcast_config_for_job(
                    self.job, min_receivers=len(self.job.authorized_clients),
                )
                self.control.run_multicast_restore_job(
                    self.repository_path, self.manifest_path,
                    trusted_public_key=self.config.server_minisign_public_key,
                    udpcast_config=udpcast,
                )
            else:
                mac = self.job.authorized_clients[0]
                trusted_key = (
                    self.config.server_minisign_public_key
                    if self.job.operation == "restore"
                    else self.config.client_minisign_public_keys.get(mac)
                )
                self.control.run_one_client_job(
                    self.repository_path,
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
        repository_lock_fd = None
        try:
            if self.job.operation == "restore" and self.job.repository_id is not None:
                from feclora.storage.repository_manager import RemoteRepositoryManager
                manager = RemoteRepositoryManager()
                try:
                    repository_lock_fd = manager.acquire_usage_lock(self.job.repository_id)
                    # Re-resolve only after acquiring the lease: an unmount that
                    # won the race after construction must not leave a stale path.
                    self.repository_path = manager.resolve(self.job.repository_id, write=False)
                    self.manifest_path = str(Path(self.repository_path) / (self.job.image_id + ".manifest.json"))
                    signature_path = self.manifest_path + ".minisig"
                    if os.path.lexists(signature_path):
                        if not self.config.server_minisign_public_key:
                            raise DeploymentServiceError("selected image is signed but no independently trusted Server minisign key is configured")
                        verify_manifest_signature(self.manifest_path, self.config.server_minisign_public_key)
                except Exception as exc:
                    raise DeploymentServiceError(
                        f"selected image repository cannot be leased and verified for this restore: {exc}"
                    ) from exc
            recover_stale_runtime_artifacts(lock_held=True)
            if (self._pxe_state is not None
                    and self._pxe_state["interface"] == self.job.network_interface):
                self.firewall.adopt(self.job.network_interface, self._pxe_state["firewall"])
            self.journal({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": self.job.job_id,
                "event": "service_started",
                "job_state": self.coordinator.state.value,
                "detail": "Persistent Server control service started; no storage operation armed.",
            })
            service_start_recorded = True
            self.firewall.on_change = self._firewall_changed
            self.control.start(
                self.config.bind_address, self.config.port,
                firewall_state_callback=self._write_firewall_state,
            )
            self.ipc.start()
            while not self._stop_event.wait(0.5):
                pass
        finally:
            try:
                self.ipc.stop()
                # A service stop must never tear down an control session
                # while the worker may be writing a target disk. Let the active
                # engine reach its own terminal state before closing TLS sessions.
                if self._worker is not None and self._worker.is_alive():
                    self._worker.join()
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
                    if repository_lock_fd is not None:
                        os.close(repository_lock_fd)
                        repository_lock_fd = None
                    if self._lock_fd is not None:
                        os.close(self._lock_fd)
                        self._lock_fd = None

    def stop(self) -> None:
        self._stop_event.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feclora persistent deployment Server service")
    parser.add_argument("--job-id")
    parser.add_argument("--recover-runtime", action="store_true")
    args = parser.parse_args(argv)
    if args.recover_runtime:
        try:
            recover_stale_runtime_artifacts()
            return 0
        except Exception as exc:
            print(f"feclora deployment runtime recovery: {exc}", file=sys.stderr)
            return 1
    if not args.job_id:
        parser.error("--job-id is required unless --recover-firewall is selected")
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
