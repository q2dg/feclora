"""Persistent Cockpit-driven Client job runtime."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from feclora.deployment.client_runtime import execute_client_image_job
from feclora.deployment.control import (
    DeploymentControlError, LocalTargetApproval, join_deployment,
)
from feclora.deployment.runtime_config import load_client_runtime_config
from feclora.network.remote_clone_protocol import create_mutual_tls_context
from feclora.storage.inventory import collect_inventory
from feclora.storage.source_safety import SourceSafetyError, check_capture_source_safe


CLIENT_JOB_DIRECTORY = Path("/var/lib/feclora/client-jobs")
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
        CLIENT_JOB_DIRECTORY / "active.lock",
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
    _ensure_directory()
    _request_path, status_path, lock_path = _job_paths(job_id)
    if not status_path.exists():
        return
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ClientJobServiceError("Client job lock file is unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ClientJobServiceError("Client job is still active; refusing interrupted-state update") from exc
        status = _read_private_json(status_path, limit=16384)
        if status.get("phase") not in TERMINAL_PHASES:
            status.update({
                "phase": "interrupted",
                "success": False,
                "detail": "Client service exited before a terminal result. No automatic reconnect or storage resume was attempted.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            _write_private_json(status_path, status)
    finally:
        os.close(fd)


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
            "success": None, "detail": "", "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _acquire_lock(self) -> None:
        _ensure_directory()
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
                    progress: dict[str, int | None] | None = None) -> None:
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
            _write_private_json(self.status_path, self._status)

    @staticmethod
    def _find_device(device_path: str, target_type: str) -> dict[str, Any]:
        inventory = collect_inventory()
        expected_type = "disk" if target_type == "disk" else "part"
        matches: list[dict[str, Any]] = []

        def visit(items: list[dict[str, Any]]) -> None:
            for item in items:
                if item.get("path") == device_path and item.get("type") == expected_type:
                    matches.append(item)
                children = item.get("children")
                if isinstance(children, list):
                    visit(children)

        visit(inventory.get("devices", []))
        if len(matches) != 1:
            raise ClientJobServiceError("selected local target is not uniquely present in the current block-device inventory")
        return matches[0]

    def run(self) -> None:
        self._acquire_lock()
        try:
            request = _read_private_json(self.request_path)
            expected = {"schema_version", "job_id", "host", "device_path", "confirmation", "compression"}
            if set(request) != expected or request.get("schema_version") != 1 or request.get("job_id") != self.job_id:
                raise ClientJobServiceError("Client job request has an invalid schema or job identifier")
            host = request["host"]
            device_path = request["device_path"]
            confirmation = request["confirmation"]
            compression = request["compression"]
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
            self.request_path.unlink()
            config = load_client_runtime_config("/etc/feclora/deployment-client.json")
            if config.local_minisign_secret_key is None and config.local_minisign_public_key is None:
                if compression != "gzip":
                    raise ClientJobServiceError("compression choice is only configurable for an image-capture Client")
            context = create_mutual_tls_context(
                "client", ca_file=config.ca_file,
                certificate_file=config.certificate_file,
                private_key_file=config.private_key_file,
            )
            self._set_status("connecting", detail="Connecting to the authenticated Server; no local disk operation has started.")

            def prepare_local_target(job):
                if job.job_id != self.job_id or job.transport != "unicast":
                    raise DeploymentControlError("Server job does not match this Client service request or transport")
                if job.operation == "save" and job.target_type != "disk":
                    raise DeploymentControlError("Client capture currently supports whole-disk jobs only")
                if job.operation == "save" and (
                    not config.local_minisign_secret_key or not config.local_minisign_public_key
                ):
                    raise DeploymentControlError("this Client has no enrolled image-signing key and cannot capture images")
                selected = self._find_device(device_path, job.target_type)
                try:
                    info = os.lstat(device_path)
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
                    if job.operation == "restore"
                    else f"READ {device_path} TO {config.server_identity}"
                )
                if confirmation != required:
                    raise DeploymentControlError("local typed target confirmation does not match the selected device and Server")
                description = " ".join(
                    str(value).replace("/dev/", "device ").replace("\n", " ")
                    for value in (
                        selected.get("model"), selected.get("size_bytes"), selected.get("serial"),
                    ) if value
                ) or ("Selected local partition" if job.target_type == "partition" else "Selected local whole disk")
                description = " ".join(description.split())[:200]
                self._set_status("ready", detail="Local target is present and explicitly approved. Waiting for the Server operator to arm the job.",
                                 target_description=description)
                return LocalTargetApproval(device_path, description, confirmation)

            def execute_job(job, tls_socket, approval):
                self._set_status("running", detail="Server armed the job. Client storage operation is in progress.")
                level = None if compression == "none" else 6

                def progress(current: int, total: int | None) -> None:
                    self._set_status("running", progress={
                        "completed_bytes": max(0, int(current)),
                        "total_bytes": max(0, int(total)) if total is not None else None,
                    })

                return execute_client_image_job(
                    job, tls_socket, approval,
                    server_identity=config.server_identity,
                    repository=config.repository,
                    trusted_server_public_key=config.trusted_server_public_key,
                    local_minisign_secret_key=config.local_minisign_secret_key,
                    local_minisign_public_key=config.local_minisign_public_key,
                    age_identity_file=config.age_identity_file,
                    age_recipients_file=config.age_recipients_file,
                    compression=compression,
                    compression_level=level,
                    progress_callback=progress,
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
                    timeout=86400,
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
        ClientDeploymentService(args.job_id).run()
        return 0
    except Exception as exc:
        print(f"feclora Client service: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
