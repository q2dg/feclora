"""Durable definitions and append-only event journal for local storage jobs.

This module deliberately does not execute storage commands. A privileged worker
must load a validated definition, revalidate its target and authorization, and
then perform the operation. Interrupted jobs are never replayed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import posixpath
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_DIRECTORY = Path("/var/lib/feclora/local-operations")
MAX_DEFINITION_BYTES = 16 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 32 * 1024 * 1024
ZERO_HASH = "0" * 64

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "interrupted"})
TRANSITIONS = {
    "queued": {"preflight", "cancelled", "interrupted"},
    "preflight": {"running", "failed", "cancelled", "interrupted"},
    "running": {"verifying", "completed", "failed", "cancelled", "interrupted"},
    "verifying": {"completed", "failed", "interrupted"},
}
DEVICE_RE = re.compile(r"/dev/[A-Za-z0-9_.!/+:-]{1,120}")

class LocalOperationError(RuntimeError):
    """A local operation definition or journal is invalid or unsafe."""

def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LocalOperationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result

def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")

def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def _safe_directory(path: Path, *, create: bool) -> int:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                     | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise LocalOperationError(f"operation directory is unavailable: {exc}") from exc
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        os.close(fd)
        raise LocalOperationError("operation directory must be a private directory owned by the service user")
    os.fchmod(fd, 0o700)
    return fd

def validate_definition(value: Any) -> dict[str, Any]:
    """Validate the versioned, allowlisted operation contract without I/O."""
    if not isinstance(value, dict):
        raise LocalOperationError("operation definition must be a JSON object")
    required = {"schema_version", "operation_id", "action", "params"}
    if set(value) != required:
        raise LocalOperationError("operation definition must contain exactly schema_version, operation_id, action and params")
    if isinstance(value["schema_version"], bool) or value["schema_version"] != SCHEMA_VERSION:
        raise LocalOperationError("unsupported local operation schema_version")
    try:
        operation_id = str(uuid.UUID(value["operation_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LocalOperationError("operation_id must be a UUID") from exc
    if operation_id != value["operation_id"]:
        raise LocalOperationError("operation_id must use canonical UUID form")
    action, params = value["action"], value["params"]
    fields = {
        "capture_disk": {"source", "image_id", "compression", "encrypt", "repository_id", "sftp_publish", "encrypt_passphrase"},
        "capture_partition": {"source", "image_id", "partition_id", "compression", "encrypt", "repository_id", "sftp_publish"},
        "capture_logical_volume": {"source", "image_id", "compression", "encrypt", "repository_id", "sftp_publish"},
        "restore_disk": {"image_id", "target", "confirmation", "repository_id", "sftp_source"},
        "restore_partition": {"image_id", "target", "confirmation", "repository_id", "sftp_source"},
        "restore_logical_volume": {"image_id", "target", "confirmation", "repository_id"},
        "clone_disk": {"source", "target", "confirmation"},
        "clone_partition": {"source", "target", "confirmation"},
        "extract_partition_image": {"image_id", "selector", "repository_id"},
        "sftp_inventory": {"host", "username", "remote_directory", "identity_credential", "known_hosts_credential", "port"},
        "sftp_fetch": {"host", "username", "remote_directory", "identity_credential", "known_hosts_credential", "port"},
        "sftp_publish": {"image_id", "host", "username", "remote_directory", "identity_credential", "known_hosts_credential", "port"},
    }
    if not isinstance(action, str) or action not in fields or not isinstance(params, dict):
        raise LocalOperationError("unsupported local storage operation")
    allowed = fields[action]
    if action.startswith("restore_"):
        accepted = (allowed, allowed - {"repository_id"}, allowed - {"sftp_source"},
                    allowed - {"repository_id", "sftp_source"})
    else:
        accepted = (allowed, allowed - {"repository_id"}, allowed - {"sftp_publish"},
                    allowed - {"repository_id", "sftp_publish"})
    if action == "capture_disk":
        accepted = accepted + tuple(item - {"encrypt_passphrase"} for item in accepted)
    if set(params) not in accepted and not (action in {"sftp_inventory", "sftp_fetch", "sftp_publish"} and set(params) == allowed - {"port"}):
        raise LocalOperationError("operation parameters do not match the selected operation")
    if "sftp_source" in params and "repository_id" in params:
        raise LocalOperationError("SFTP restore source cannot be combined with a mounted repository")
    for key in ("source", "target"):
        if key in params:
            device = params[key]
            if (not isinstance(device, str) or not DEVICE_RE.fullmatch(device)
                    or ".." in device.split("/") or os.path.normpath(device) != device):
                raise LocalOperationError(f"{key} must be a normalized /dev device path")
    for key in ("image_id", "partition_id"):
        if key in params and (not isinstance(params[key], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", params[key])):
            raise LocalOperationError(f"{key} is invalid")
    if "repository_id" in params and (not isinstance(params["repository_id"], str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", params["repository_id"])):
        raise LocalOperationError("repository_id is invalid")
    if action == "sftp_inventory":
        config = params
        if (not isinstance(config.get("host"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", config["host"])
                or config["host"].endswith(".") or ".." in config["host"]):
            raise LocalOperationError("SFTP inventory host is invalid")
        if not isinstance(config.get("username"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", config["username"]):
            raise LocalOperationError("SFTP inventory username is invalid")
        remote = config.get("remote_directory")
        if (not isinstance(remote, str) or not re.fullmatch(r"/[A-Za-z0-9._/-]{0,1024}", remote)
                or remote.startswith("//") or posixpath.normpath(remote) != remote
                or (remote != "/" and any(part in {"", ".", ".."} for part in remote.split("/")[1:]))):
            raise LocalOperationError("SFTP inventory directory must be absolute and normalized")
        for field in ("identity_credential", "known_hosts_credential"):
            credential_value = config.get(field)
            if not isinstance(credential_value, str) or not re.fullmatch(
                r"/etc/credstore\.encrypted/feclora/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.cred", credential_value
            ):
                raise LocalOperationError(f"SFTP inventory {field} must reference a registered encrypted credential")
        port = config.get("port", 22)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise LocalOperationError("SFTP inventory port is invalid")

    if action in {"sftp_fetch", "sftp_publish"}:
        config = params
        if (not isinstance(config.get("host"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", config["host"])
                or config["host"].endswith(".") or ".." in config["host"]):
            raise LocalOperationError("SFTP transfer host is invalid")
        if not isinstance(config.get("username"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", config["username"]):
            raise LocalOperationError("SFTP transfer username is invalid")
        remote = config.get("remote_directory")
        if (not isinstance(remote, str) or not re.fullmatch(r"/[A-Za-z0-9._/-]{0,1024}", remote)
                or remote.startswith("//") or posixpath.normpath(remote) != remote
                or (remote != "/" and any(part in {"", ".", ".."} for part in remote.split("/")[1:]))):
            raise LocalOperationError("SFTP transfer directory must be absolute and normalized")
        for field in ("identity_credential", "known_hosts_credential"):
            credential_value = config.get(field)
            if not isinstance(credential_value, str) or not re.fullmatch(
                r"/etc/credstore[.]encrypted/feclora/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}[.]cred", credential_value
            ):
                raise LocalOperationError(f"SFTP transfer {field} must reference a registered encrypted credential")
        port = config.get("port", 22)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise LocalOperationError("SFTP port must be an integer between 1 and 65535")
    if "sftp_source" in params:
        config = params["sftp_source"]
        required_sftp = {"host", "username", "remote_directory", "identity_credential", "known_hosts_credential", "expected_manifest_sha256"}
        if not isinstance(config, dict) or set(config) not in (required_sftp, required_sftp | {"port"}):
            raise LocalOperationError("SFTP restore source settings are invalid")
        if not isinstance(config.get("expected_manifest_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", config["expected_manifest_sha256"]):
            raise LocalOperationError("SFTP restore source must be bound to an inspected manifest SHA-256")
        if (not isinstance(config.get("host"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", config["host"])
                or config["host"].endswith(".") or ".." in config["host"]):
            raise LocalOperationError("SFTP restore source host is invalid")
        if not isinstance(config.get("username"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", config["username"]):
            raise LocalOperationError("SFTP restore source username is invalid")
        remote = config.get("remote_directory")
        if (not isinstance(remote, str) or not re.fullmatch(r"/[A-Za-z0-9._/-]{0,1024}", remote)
                or remote.startswith("//") or posixpath.normpath(remote) != remote
                or (remote != "/" and any(part in {"", ".", ".."} for part in remote.split("/")[1:]))):
            raise LocalOperationError("SFTP restore source directory must be absolute and normalized")
        for field in ("identity_credential", "known_hosts_credential"):
            credential_value = config.get(field)
            if not isinstance(credential_value, str) or not re.fullmatch(
                r"/etc/credstore\.encrypted/feclora/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.cred", credential_value
            ):
                raise LocalOperationError(f"SFTP restore source {field} must reference a registered encrypted credential")
        port = config.get("port", 22)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise LocalOperationError("SFTP port must be an integer between 1 and 65535")
    if action.startswith("restore_") or action.startswith("clone_"):
        target = params.get("target")
        if params.get("confirmation") != f"ERASE {target}" and not (
            action == "clone_partition" and params.get("confirmation") == f"ERASE {target} FROM {params.get('source')}"
        ):
            raise LocalOperationError("destructive operation confirmation does not match its target")
    if action in {"capture_disk", "capture_partition"}:
        if params.get("compression") not in {"none", "gzip", "zstd", "lz4"}:
            raise LocalOperationError("unsupported compression")
        if not all(isinstance(params.get(key), bool) for key in ("encrypt")):
            raise LocalOperationError("encrypt must be boolean")
        if "encrypt_passphrase" in params:
            if not isinstance(params["encrypt_passphrase"], bool):
                raise LocalOperationError("encrypt_passphrase must be boolean")
            if params["encrypt_passphrase"] and not params.get("encrypt"):
                raise LocalOperationError("passphrase encryption requires encrypt=true")
            if action != "capture_disk" and params["encrypt_passphrase"]:
                raise LocalOperationError("passphrase encryption is currently supported only for whole-disk capture")
        if "sftp_publish" in params:
            config = params["sftp_publish"]
            required_sftp = {"host", "username", "remote_directory", "identity_credential", "known_hosts_credential"}
            if not isinstance(config, dict) or set(config) not in (required_sftp, required_sftp | {"port"}):
                raise LocalOperationError("SFTP publication settings are invalid")
            if (not isinstance(config.get("host"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", config["host"])
                    or config["host"].endswith(".") or ".." in config["host"]):
                raise LocalOperationError("SFTP publication host is invalid")
            if not isinstance(config.get("username"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", config["username"]):
                raise LocalOperationError("SFTP publication username is invalid")
            remote = config.get("remote_directory")
            if (not isinstance(remote, str) or not re.fullmatch(r"/[A-Za-z0-9._/-]{0,1024}", remote)
                    or remote.startswith("//") or posixpath.normpath(remote) != remote
                    or (remote != "/" and any(part in {"", ".", ".."} for part in remote.split("/")[1:]))):
                raise LocalOperationError("SFTP publication remote directory must be absolute and normalized")
            for field in ("identity_credential", "known_hosts_credential"):
                credential_value = config.get(field)
                if not isinstance(credential_value, str) or not re.fullmatch(
                    r"/etc/credstore\.encrypted/feclora/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.cred", credential_value
                ):
                    raise LocalOperationError(f"SFTP publication {field} must reference a registered encrypted credential")
            port = config.get("port", 22)
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise LocalOperationError("SFTP publication port is invalid")
    if action == "extract_partition_image" and (
        not isinstance(params.get("selector"), str) or not params["selector"] or len(params["selector"]) > 256
    ):
        raise LocalOperationError("selector is invalid")
    # Return a detached JSON-compatible copy; never retain caller-owned mappings.
    try:
        encoded = _canonical(value)
        if len(encoded) > MAX_DEFINITION_BYTES:
            raise LocalOperationError("operation definition exceeds the size limit")
        return json.loads(encoded.decode("ascii"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise LocalOperationError(f"operation definition is not valid JSON data: {exc}") from exc

class LocalOperationStore:
    """Persist immutable job definitions and hash-chained state/progress events."""

    def __init__(self, directory: str | os.PathLike[str] = DEFAULT_DIRECTORY):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = _safe_directory(self.directory, create=False)
        os.close(fd)

    def _name(self, operation_id: str, suffix: str) -> str:
        try:
            normalized = str(uuid.UUID(operation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise LocalOperationError("operation_id must be a UUID") from exc
        if normalized != operation_id:
            raise LocalOperationError("operation_id must use canonical UUID form")
        return f"{normalized}.{suffix}"

    def submit(self, action: str, params: dict[str, Any], *, operation_id: str | None = None) -> str:
        identifier = operation_id or str(uuid.uuid4())
        definition = validate_definition({
            "schema_version": SCHEMA_VERSION, "operation_id": identifier,
            "action": action, "params": params,
        })
        payload = _canonical(definition)
        directory_fd = _safe_directory(self.directory, create=False)
        try:
            fd = os.open(self._name(identifier, "json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory_fd)
            try:
                os.write(fd, payload + b"\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory_fd)
        except FileExistsError as exc:
            raise LocalOperationError("operation identifier already exists") from exc
        except OSError as exc:
            raise LocalOperationError(f"cannot persist operation definition: {exc}") from exc
        finally:
            os.close(directory_fd)
        details = {"action": action}
        for key in ("source", "target", "image_id"):
            if key in definition["params"]:
                details[key] = definition["params"][key]
        self.append(identifier, "queued", details)
        return identifier

    def definition(self, operation_id: str) -> dict[str, Any]:
        name = self._name(operation_id, "json")
        directory_fd = _safe_directory(self.directory, create=False)
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > MAX_DEFINITION_BYTES:
                    raise LocalOperationError("operation definition permissions or size are unsafe")
                raw = os.read(fd, MAX_DEFINITION_BYTES + 1)
            finally:
                os.close(fd)
        except OSError as exc:
            raise LocalOperationError(f"cannot read operation definition: {exc}") from exc
        finally:
            os.close(directory_fd)
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LocalOperationError("operation definition is invalid JSON") from exc
        return validate_definition(value)

    def events(self, operation_id: str) -> list[dict[str, Any]]:
        name = self._name(operation_id, "jsonl")
        directory_fd = _safe_directory(self.directory, create=False)
        try:
            try:
                fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            except FileNotFoundError:
                return []
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > MAX_JOURNAL_BYTES:
                    raise LocalOperationError("operation journal permissions or size are unsafe")
                chunks, remaining = [], info.st_size
                while remaining:
                    part = os.read(fd, min(1024 * 1024, remaining))
                    if not part:
                        raise LocalOperationError("operation journal was truncated while reading")
                    chunks.append(part)
                    remaining -= len(part)
                raw = b"".join(chunks)
            finally:
                os.close(fd)
        finally:
            os.close(directory_fd)
        if raw and not raw.endswith(b"\n"):
            raise LocalOperationError("operation journal ends with an incomplete event")
        result, previous = [], ZERO_HASH
        for sequence, line in enumerate(raw.splitlines(), 1):
            if not line or len(line) > MAX_EVENT_BYTES:
                raise LocalOperationError("operation journal contains an empty or oversized event")
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise LocalOperationError(f"operation event {sequence} is invalid JSON") from exc
            if (not isinstance(event, dict) or event.get("sequence") != sequence
                    or event.get("previous_hash") != previous or event.get("operation_id") != operation_id):
                raise LocalOperationError(f"operation journal chain is broken at event {sequence}")
            digest = event.pop("event_hash", None)
            if hashlib.sha256(_canonical(event)).hexdigest() != digest:
                raise LocalOperationError(f"operation event hash mismatch at event {sequence}")
            event["event_hash"] = digest
            previous = digest
            result.append(event)
        return result

    def append(self, operation_id: str, state: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        if state not in set(TRANSITIONS) | TERMINAL_STATES | {"progress"}:
            raise LocalOperationError("unsupported operation state")
        name = self._name(operation_id, "jsonl")
        definition = self.definition(operation_id)
        directory_fd = _safe_directory(self.directory, create=False)
        try:
            fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                         0o600, dir_fd=directory_fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                    raise LocalOperationError("operation journal permissions or ownership are unsafe")
                history = self.events(operation_id)
                current = next((item["state"] for item in reversed(history) if item["state"] != "progress"), None)
                if current is None:
                    if state != "queued":
                        raise LocalOperationError("first operation event must be queued")
                elif state == "progress":
                    if current != "running":
                        raise LocalOperationError("progress is only valid while an operation is running")
                elif state not in TRANSITIONS.get(current, set()):
                    raise LocalOperationError(f"invalid operation transition: {current} -> {state}")
                payload_details = details or {}
                if not isinstance(payload_details, dict):
                    raise LocalOperationError("event details must be an object")
                event = {
                    "schema_version": SCHEMA_VERSION, "operation_id": operation_id,
                    "sequence": len(history) + 1, "timestamp": _timestamp(),
                    "state": state, "details": payload_details,
                    "previous_hash": history[-1]["event_hash"] if history else ZERO_HASH,
                }
                event["event_hash"] = hashlib.sha256(_canonical(event)).hexdigest()
                encoded = _canonical(event) + b"\n"
                if len(encoded) > MAX_EVENT_BYTES or info.st_size + len(encoded) > MAX_JOURNAL_BYTES:
                    raise LocalOperationError("operation journal size limit exceeded")
                view = memoryview(encoded)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise LocalOperationError("short write while appending operation event")
                    view = view[written:]
                os.fsync(fd)
                os.fsync(directory_fd)
                return event
            finally:
                os.close(fd)
        except LocalOperationError:
            raise
        except OSError as exc:
            raise LocalOperationError(f"cannot append operation event: {exc}") from exc
        finally:
            os.close(directory_fd)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent durable jobs without trusting directory entry types."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise LocalOperationError("operation list limit must be between 1 and 500")
        directory_fd = _safe_directory(self.directory, create=False)
        try:
            names = sorted(
                (entry.name for entry in os.scandir(directory_fd)
                 if re.fullmatch(r"[0-9a-f-]{36}\.json", entry.name)),
                reverse=True,
            )[:limit]
        finally:
            os.close(directory_fd)
        reports = []
        for name in names:
            operation_id = name[:-5]
            reports.append(self.status(operation_id))
        return reports

    def operation_ids(self) -> list[str]:
        """Enumerate every job definition without parsing its event journal."""
        directory_fd = _safe_directory(self.directory, create=False)
        try:
            names = sorted(
                (entry.name for entry in os.scandir(directory_fd)
                 if re.fullmatch(r"[0-9a-f-]{36}\.json", entry.name)),
                reverse=True,
            )
        finally:
            os.close(directory_fd)
        return [name[:-5] for name in names]

    def list_all(self) -> list[dict[str, Any]]:
        """Return every durable job; recovery must never be limited to recent history."""
        return [self.status(operation_id) for operation_id in self.operation_ids()]

    def status(self, operation_id: str) -> dict[str, Any]:
        definition = self.definition(operation_id)
        history = self.events(operation_id)
        if not history:
            raise LocalOperationError("operation has no state history")
        current_state = next((item["state"] for item in reversed(history) if item["state"] != "progress"), None)
        return {"operation_id": operation_id, "action": definition["action"],
                "state": current_state, "events": history}

    def mark_interrupted(self, operation_id: str, reason: str = "worker exited; operation was not resumed") -> dict[str, Any]:
        history = self.events(operation_id)
        if not history:
            raise LocalOperationError("operation has no state history")
        current = history[-1]["state"]
        if current in TERMINAL_STATES:
            return history[-1]
        return self.append(operation_id, "interrupted", {"reason": reason[:512]})
