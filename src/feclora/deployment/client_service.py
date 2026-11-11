"""Persistent Cockpit-driven Client job runtime."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import shutil
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from feclora.deployment.client_runtime import execute_client_image_job
from feclora.deployment.multicast_runtime import execute_multicast_restore
from feclora.deployment.control import (
    DeploymentControlError, LocalTargetApproval, join_deployment, send_control_message,
)
from feclora.deployment.runtime_config import load_client_runtime_config
from feclora.network.remote_clone_protocol import create_mutual_tls_context
from feclora.network.firewall import PXEFirewall
from feclora.network.multicast_preflight import inspect_multicast_interface
from feclora.storage.inventory import collect_inventory
from feclora.storage.source_safety import SourceSafetyError, check_capture_source_safe


CLIENT_JOB_DIRECTORY = Path("/var/lib/feclora/client-jobs")
RUNTIME_DIRECTORY = Path("/run/feclora")
JOB_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
TERMINAL_PHASES = {"completed", "failed", "cancelled", "interrupted"}


class ClientJobServiceError(RuntimeError):
    """Raised when a local Client job request or lifecycle is unsafe."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Client job field")
        result[key] = value
    return result


def _job_paths(job_id: str) -> tuple[Path, Path, Path]:
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ClientJobServiceError("job_id must be a canonical UUID")
    return (
        CLIENT_JOB_DIRECTORY / f"{job_id}.request.json",
        CLIENT_JOB_DIRECTORY / f"{job_id}.status.json",
        RUNTIME_DIRECTORY / "deployment.lock",
    )


def _ensure_directory() -> None:
    try:
        CLIENT_JOB_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(CLIENT_JOB_DIRECTORY)
    except OSError as exc:
        raise ClientJobServiceError(f"cannot prepare private Client job directory: {exc}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o077):
        raise ClientJobServiceError("Client job directory must be a private root-owned real directory")


def _ensure_runtime_directory() -> None:
    try:
        RUNTIME_DIRECTORY.mkdir(mode=0o755, parents=True, exist_ok=True)
        info = os.lstat(RUNTIME_DIRECTORY)
    except OSError as exc:
        raise ClientJobServiceError(f"cannot prepare deployment runtime directory: {exc}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_mode & 0o022):
        raise ClientJobServiceError("deployment runtime directory is unsafe")


def _read_private_json(path: Path, *, limit: int = 8192) -> dict[str, Any]:
    try:
        info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > limit):
            raise ClientJobServiceError(f"private Client job file is unsafe: {path.name}")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0
                    or opened.st_mode & 0o077
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise ClientJobServiceError(f"private Client job file changed during inspection: {path.name}")
            raw = os.read(fd, limit + 1)
        finally:
            os.close(fd)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except ClientJobServiceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ClientJobServiceError(f"cannot read private Client job file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClientJobServiceError("private Client job document must be a JSON object")
    return value


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    _ensure_directory()
    if os.path.lexists(path):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
            raise ClientJobServiceError(f"refusing to overwrite unsafe Client job file: {path.name}")
    fd, temporary = tempfile.mkstemp(prefix=".client-job-", dir=CLIENT_JOB_DIRECTORY)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(CLIENT_JOB_DIRECTORY, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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


def mark_client_job_interrupted(job_id: str) -> None:
    """Mark a nonterminal Client record after its systemd process has exited."""
    _ensure_directory()
    _request_path, status_path, _lock_path = _job_paths(job_id)
    if not os.path.lexists(status_path):
        return
    status = _read_private_json(status_path, limit=16384)
    if status.get("phase") not in TERMINAL_PHASES:
        status.update({
            "phase": "interrupted",
            "success": False,
            "detail": "Client service exited before a terminal result. No automatic reconnect or storage resume was attempted.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        _write_private_json(status_path, status)



class ClientDeploymentService:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.request_path, self.status_path, self.lock_path = _job_paths(job_id)
        self._lock_fd: int | None = None
        self._status_lock = threading.RLock()
        self._phase = "created"
        self._status: dict[str, Any] = {
            "schema_version": 1, "job_id": job_id, "phase": "created",
            "target_description": None, "progress": None,
            "network_interface": None, "multicast_warnings": [],
            "success": None, "detail": "", "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _acquire_lock(self) -> None:
        _ensure_directory()
        _ensure_runtime_directory()
        self._lock_fd = os.open(
            self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        info = os.fstat(self._lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ClientJobServiceError("Client job lock file is unsafe")
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ClientJobServiceError("another Client service already owns this job") from exc

    def _set_status(self, phase: str, *, detail: str | None = None,
                    success: bool | None = None, target_description: str | None = None,
                    progress: dict[str, int | None] | None = None,
                    network_interface: str | None = None,
                    multicast_warnings: list[str] | None = None) -> None:
        with self._status_lock:
            self._phase = phase
            self._status.update({
                "phase": phase,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            if detail is not None:
                self._status["detail"] = detail[:1024]
            if success is not None:
                self._status["success"] = success
            if target_description is not None:
                self._status["target_description"] = target_description[:256]
            if progress is not None:
                self._status["progress"] = progress
            if network_interface is not None:
                self._status["network_interface"] = network_interface
            if multicast_warnings is not None:
                self._status["multicast_warnings"] = list(multicast_warnings)
            _write_private_json(self.status_path, self._status)

    @staticmethod
    def _find_device(device_path: str, target_type: str) -> dict[str, Any]:
        inventory = collect_inventory()
        if target_type == "logical_volume":
            topology = inventory.get("volume_topology", {})
            if topology.get("status") != "available":
                raise ClientJobServiceError("LVM topology is unavailable for local target validation")
            devices: list[dict[str, Any]] = []

            def visit(items: list[dict[str, Any]]) -> None:
                for item in items:
                    if isinstance(item, dict):
                        devices.append(item)
                        children = item.get("children")
                        if isinstance(children, list):
                            visit(children)

            visit(inventory.get("devices", []))
            all_lvs = [
                lv for group in topology.get("volume_groups", [])
                for lv in group.get("logical_volumes", [])
                if isinstance(lv, dict) and lv.get("major_minor")
            ]
            identity_counts: dict[str, int] = {}
            for lv in all_lvs:
                identity_counts[lv["major_minor"]] = identity_counts.get(lv["major_minor"], 0) + 1
            matches: list[dict[str, Any]] = []
            for group in topology.get("volume_groups", []):
                if group.get("status") != "healthy":
                    continue
                for lv in group.get("logical_volumes", []):
                    if (not isinstance(lv, dict) or lv.get("path") != device_path
                            or lv.get("segment_type") not in {"linear", "thin"}
                            or lv.get("snapshot") or lv.get("hidden")
                            or lv.get("health") not in (None, "", "-", "ok", "healthy")
                            or not lv.get("major_minor")
                            or identity_counts.get(lv["major_minor"]) != 1):
                        continue
                    backing = [item for item in devices if item.get("major_minor") == lv["major_minor"]]
                    if len(backing) == 1 and backing[0].get("type") == "lvm":
                        matches.append({**backing[0], **lv, "path": lv["path"], "type": "lvm"})
            if len(matches) != 1:
                raise ClientJobServiceError("selected logical volume is not uniquely present in healthy local LVM inventory")
            return matches[0]

        expected_type = "disk" if target_type == "disk" else "part"
        matches: list[dict[str, Any]] = []

        def visit_devices(items: list[dict[str, Any]]) -> None:
            for item in items:
                if item.get("path") == device_path and item.get("type") == expected_type:
                    matches.append(item)
                children = item.get("children")
                if isinstance(children, list):
                    visit_devices(children)

        visit_devices(inventory.get("devices", []))
        if len(matches) != 1:
            raise ClientJobServiceError("selected local target is not uniquely present in the current block-device inventory")
        return matches[0]

    def _handle_signal(self, _signum: int, _frame: Any) -> None:
        if self._phase == "running":
            # Do not interrupt a block-device operation during orderly shutdown.
            return
        raise SystemExit(0)

    def run(self) -> None:
        self._acquire_lock()
        try:
            from feclora.deployment.service import recover_stale_runtime_artifacts
            recover_stale_runtime_artifacts(lock_held=True)
            request = _read_private_json(self.request_path)
            expected = {"schema_version", "job_id", "host", "device_path", "confirmation", "compression", "network_interface", "igmp_confirmed"}
            optional = {"source_address", "image_encrypt", "image_sign"}
            if (not expected.issubset(request) or set(request) - expected - optional
                    or request.get("schema_version") != 1 or request.get("job_id") != self.job_id):
                raise ClientJobServiceError("Client job request has an invalid schema or job identifier")
            host = request["host"]
            device_path = request["device_path"]
            confirmation = request["confirmation"]
            compression = request["compression"]
            network_interface = request["network_interface"]
            source_address = request.get("source_address")
            igmp_confirmed = request["igmp_confirmed"]
            image_encrypt = request.get("image_encrypt", False)
            image_sign = request.get("image_sign", False)
            if not isinstance(image_encrypt, bool) or not isinstance(image_sign, bool):
                raise ClientJobServiceError("per-image encryption/signing choices must be boolean")
            if not isinstance(igmp_confirmed, bool):
                raise ClientJobServiceError("IGMP network acknowledgement must be boolean")
            if (not isinstance(host, str) or not host or len(host) > 253
                    or any(ord(char) < 33 for char in host)):
                raise ClientJobServiceError("Server host is invalid")
            if (not isinstance(device_path, str) or not device_path.startswith("/dev/")
                    or len(device_path) > 256 or os.path.normpath(device_path) != device_path):
                raise ClientJobServiceError("selected local device path is invalid")
            if not isinstance(confirmation, str) or len(confirmation) > 512:
                raise ClientJobServiceError("local target confirmation is invalid")
            if not isinstance(compression, str) or compression not in {"none", "gzip", "xz"}:
                raise ClientJobServiceError("capture compression must be none, gzip or xz")
            if source_address is not None and network_interface is None:
                raise ClientJobServiceError("Client source address requires its selected interface")
            if network_interface is not None:
                if (not isinstance(network_interface, str)
                        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", network_interface)
                        or (source_address is not None and not isinstance(source_address, str))):
                    raise ClientJobServiceError("selected Client interface/source address is invalid")
                if source_address is not None:
                    from feclora.network.interface_discovery import discover_interface_addresses
                    try:
                        current_addresses = discover_interface_addresses(network_interface)
                    except Exception as exc:
                        raise ClientJobServiceError(f"selected Client interface is unavailable: {exc}") from exc
                    if source_address not in {item.address for item in current_addresses}:
                        raise ClientJobServiceError("selected Client source address is no longer assigned to its interface")
            self.request_path.unlink()
            config = load_client_runtime_config("/etc/feclora/deployment-client.json")
            context = create_mutual_tls_context(
                "client", ca_file=config.ca_file,
                certificate_file=config.certificate_file,
                private_key_file=config.private_key_file,
            )
            self._set_status("connecting", detail="Connecting to the authenticated Server; no local disk operation has started.")

            def prepare_local_target(job):
                if job.operation != "save" and (image_encrypt or image_sign):
                    raise DeploymentControlError("per-image encryption/signing selections are valid only for a save job")
                if job.job_id != self.job_id or job.transport not in {"unicast", "multicast"}:
                    raise DeploymentControlError("Server job does not match this Client service request or supported transport")
                staging_detail = ""
                if job.transport == "multicast":
                    if job.operation != "restore" or not network_interface or igmp_confirmed is not True:
                        raise DeploymentControlError("multicast Client jobs require restore, a receive interface and explicit IGMP acknowledgement")
                    try:
                        preflight = inspect_multicast_interface(
                            network_interface, job.multicast_group, role="receiver",
                        )
                    except Exception as exc:
                        raise DeploymentControlError(f"multicast receive interface preflight failed: {exc}") from exc
                    self._set_status(
                        "connecting", network_interface=network_interface,
                        multicast_warnings=list(preflight.warnings),
                    )
                    required_bytes = job.staging_required_bytes
                    if (isinstance(required_bytes, bool) or not isinstance(required_bytes, int)
                            or required_bytes < 0):
                        raise DeploymentControlError(
                            "Server did not provide a validated multicast staging requirement"
                        )
                    try:
                        free_bytes = shutil.disk_usage(config.repository).free
                    except OSError as exc:
                        raise DeploymentControlError(
                            f"cannot inspect Client staging repository capacity: {exc}"
                        ) from exc
                    reserve_bytes = 64 * 1024 * 1024
                    if free_bytes < required_bytes + reserve_bytes:
                        raise DeploymentControlError(
                            "insufficient Client staging capacity before READY: "
                            f"{free_bytes} bytes free, {required_bytes} bytes required "
                            f"plus {reserve_bytes} bytes safety reserve"
                        )
                    staging_detail = (
                        f" Multicast staging preflight passed: {required_bytes} bytes required, "
                        f"{free_bytes} bytes free, {reserve_bytes} bytes reserved."
                    )
                elif igmp_confirmed is not False:
                    raise DeploymentControlError("unicast Client job must not specify an IGMP acknowledgement")
                if job.operation == "save" and job.target_type != "disk":
                    raise DeploymentControlError("Client capture currently supports whole-disk jobs only")
                selected = self._find_device(device_path, job.target_type)
                if not job.authorizes_target(config.mac_address, selected):
                    raise DeploymentControlError(
                        "selected local target does not match this Client's job-bound WWN/serial identity"
                    )
                try:
                    info = os.stat(device_path)
                except OSError as exc:
                    raise DeploymentControlError(f"cannot inspect selected local target: {exc}") from exc
                if not stat.S_ISBLK(info.st_mode):
                    raise DeploymentControlError("selected local target is no longer a block device")
                try:
                    check_capture_source_safe(device_path)
                except SourceSafetyError as exc:
                    raise DeploymentControlError(f"selected local target is unsafe or in use: {exc}") from exc
                required = (
                    f"ERASE {device_path} FROM {config.server_identity}"
                    if job.operation in {"restore", "clone"}
                    else f"READ {device_path} TO {config.server_identity}"
                )
                if confirmation != required:
                    raise DeploymentControlError("local typed target confirmation does not match the selected device and Server")
                description = " ".join(
                    str(value).replace("/dev/", "device ").replace("\n", " ")
                    for value in (
                        selected.get("model"), selected.get("size_bytes"), selected.get("serial"),
                    ) if value
                ) or ("Selected local logical volume" if job.target_type == "logical_volume" else "Selected local partition" if job.target_type == "partition" else "Selected local whole disk")
                description = " ".join(description.split())[:200]
                self._set_status(
                    "ready", detail=(
                        "Local target is present and explicitly approved. "
                        "Waiting for the Server operator to arm the job." + staging_detail
                    ),
                    target_description=description,
                    network_interface=network_interface if job.transport == "multicast" else None,
                )
                return LocalTargetApproval(device_path, description, confirmation)

            def execute_job(job, tls_socket, approval):
                self._set_status("running", detail="Server armed the job. Client storage operation is in progress.")
                level = None if compression == "none" else 6

                last_reported_bytes = 0
                last_reported_at = 0.0
                last_reported_phase = None

                def report_progress(phase: str, current: int, total: int | None, *, report_remote: bool = True) -> None:
                    nonlocal last_reported_bytes, last_reported_at, last_reported_phase
                    completed = max(0, int(current))
                    total_bytes = max(0, int(total)) if total is not None else None
                    if phase != last_reported_phase:
                        last_reported_bytes = 0
                        last_reported_at = 0.0
                        last_reported_phase = phase
                    self._set_status("running", progress={
                        "phase": phase, "completed_bytes": completed, "total_bytes": total_bytes,
                    })
                    now = time.monotonic()
                    if report_remote and (now - last_reported_at >= 1.0
                            or completed - last_reported_bytes >= 16 * 1024 * 1024
                            or (total_bytes is not None and completed >= total_bytes)):
                        try:
                            send_control_message(tls_socket, {
                                "type": "progress", "job_id": job.job_id,
                                "phase": phase, "completed_bytes": completed,
                                "total_bytes": total_bytes,
                            })
                            last_reported_bytes = completed
                            last_reported_at = now
                        except (DeploymentControlError, OSError):
                            # Telemetry must never abort an otherwise safe local disk operation.
                            pass

                def progress(current: int, total: int | None) -> None:
                    report_progress(job.operation, current, total, report_remote=job.operation != "clone")

                def transfer_progress(current: int, total: int) -> None:
                    # Image bytes and control frames share one TLS stream. Keep
                    # transfer telemetry local; sending JSON here would corrupt
                    # the framed artifact payload in that same byte stream.
                    report_progress("transfer", current, total, report_remote=False)

                if job.transport == "multicast":
                    return execute_multicast_restore(
                        job, tls_socket, approval,
                        server_identity=config.server_identity,
                        repository=config.repository,
                        trusted_server_public_key=config.trusted_server_public_key,
                        firewall=PXEFirewall(),
                        network_interface=network_interface,
                        age_identity_file=config.age_identity_file,
                        progress_callback=progress,
                    )
                return execute_client_image_job(
                    job, tls_socket, approval,
                    server_identity=config.server_identity,
                    local_identity=config.local_identity,
                    repository=config.repository,
                    trusted_server_public_key=config.trusted_server_public_key,
                    local_minisign_secret_key=config.local_minisign_secret_key if image_sign else None,
                    local_minisign_public_key=config.local_minisign_public_key if image_sign else None,
                    age_identity_file=config.age_identity_file,
                    age_recipients_file=config.age_recipients_file if image_encrypt else None,
                    encrypt_image=image_encrypt,
                    sign_image=image_sign,
                    compression=compression,
                    compression_level=level,
                    progress_callback=progress,
                    transfer_progress_callback=transfer_progress,
                )

            try:
                job, success, detail = join_deployment(
                    host, config.port, context,
                    local_identity=config.local_identity,
                    expected_server_identity=config.server_identity,
                    mac_address=config.mac_address,
                    job_id=self.job_id,
                    prepare_local_target=prepare_local_target,
                    execute_job=execute_job,
                    timeout=86400, source_address=source_address,
                    network_interface=network_interface,
                )
                self._set_status(
                    "completed" if success else "failed",
                    success=success, detail=detail,
                )
            except DeploymentControlError as exc:
                message = str(exc)
                phase = "cancelled" if "cancelled" in message.lower() else "failed"
                self._set_status(phase, success=False, detail=message)
            except Exception as exc:
                self._set_status("failed", success=False, detail=str(exc))
        except Exception as exc:
            self._set_status("failed", success=False, detail=str(exc))
        finally:
            try:
                if self.request_path.exists():
                    self.request_path.unlink()
            except OSError:
                pass
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feclora persistent Client deployment service")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--mark-interrupted", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.mark_interrupted:
            mark_client_job_interrupted(args.job_id)
            return 0
        service = ClientDeploymentService(args.job_id)
        signal.signal(signal.SIGTERM, service._handle_signal)
        signal.signal(signal.SIGINT, service._handle_signal)
        service.run()
        return 0
    except Exception as exc:
        print(f"feclora Client service: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
