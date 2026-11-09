"""Durable, fail-closed manifest for staged deployment-CA trust migration.

This module records operator-verified progress only. It does not distribute
trust, activate TLS files, issue certificates, or authenticate remote clients.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any


class CAMigrationError(RuntimeError):
    """Invalid or unsafe CA migration state."""


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 256 * 1024
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_PHASES = ("prepared", "distributing", "trust_distributed", "server_switched",
           "converged", "retired")
_TRANSITIONS = {
    "prepared": {"distributing"}, "distributing": {"trust_distributed"},
    "trust_distributed": {"server_switched"}, "server_switched": {"converged"},
    "converged": {"retired"}, "retired": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CAMigrationError("manifest contains duplicate JSON keys")
        result[key] = value
    return result


def _directory(path: str | os.PathLike[str]) -> str:
    if os.geteuid() != 0:
        raise CAMigrationError("CA migration manifests require root")
    root = os.path.abspath(os.fspath(path))
    os.makedirs(root, mode=0o700, exist_ok=True)
    info = os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise CAMigrationError("migration directory must be a real root-owned directory")
    os.chmod(root, 0o700)
    return root


def _validate(value: Any, migration_id: str | None = None) -> dict[str, Any]:
    fields = {"schema_version", "migration_id", "created_at", "updated_at",
              "old_ca_fingerprint", "new_ca_fingerprint", "phase", "clients",
              "history", "retirement_confirmed"}
    if not isinstance(value, dict) or set(value) != fields:
        raise CAMigrationError("migration manifest has an unsupported schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise CAMigrationError("unsupported CA migration manifest version")
    try:
        parsed = str(uuid.UUID(value["migration_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CAMigrationError("migration identifier is invalid") from exc
    if parsed != value["migration_id"] or (migration_id is not None and parsed != migration_id):
        raise CAMigrationError("migration identifier does not match its filename")
    for field in ("old_ca_fingerprint", "new_ca_fingerprint"):
        if not isinstance(value[field], str) or not _FINGERPRINT.fullmatch(value[field]):
            raise CAMigrationError(f"{field} must be a lowercase SHA-256 fingerprint")
    if value["old_ca_fingerprint"] == value["new_ca_fingerprint"]:
        raise CAMigrationError("old and new CA fingerprints must differ")
    if value["phase"] not in _PHASES:
        raise CAMigrationError("migration phase is invalid")
    if not isinstance(value["created_at"], str) or not isinstance(value["updated_at"], str):
        raise CAMigrationError("migration timestamps are invalid")
    if type(value["retirement_confirmed"]) is not bool:
        raise CAMigrationError("retirement confirmation flag is invalid")
    clients = value["clients"]
    if not isinstance(clients, dict) or len(clients) > 4096:
        raise CAMigrationError("migration client inventory is invalid or too large")
    for client_id, status in clients.items():
        if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
            raise CAMigrationError("migration inventory contains an invalid Client ID")
        if not isinstance(status, dict) or set(status) != {"trust_acknowledged_at", "leaf_acknowledged_at"}:
            raise CAMigrationError("migration Client status has an unsupported schema")
        for key in ("trust_acknowledged_at", "leaf_acknowledged_at"):
            if status[key] is not None and not isinstance(status[key], str):
                raise CAMigrationError("migration acknowledgement timestamp is invalid")
        if status["leaf_acknowledged_at"] is not None and status["trust_acknowledged_at"] is None:
            raise CAMigrationError("Client leaf acknowledgement lacks a prior trust acknowledgement")
    history = value["history"]
    if not isinstance(history, list) or not 1 <= len(history) <= 64:
        raise CAMigrationError("migration history is invalid")
    if any(not isinstance(event, dict) or set(event) != {"phase", "at"}
           or event["phase"] not in _PHASES or not isinstance(event["at"], str) for event in history):
        raise CAMigrationError("migration history event is invalid")
    phases = [event["phase"] for event in history]
    if phases[0] != "prepared" or phases[-1] != value["phase"]:
        raise CAMigrationError("migration history does not match its current phase")
    for before, after in zip(phases, phases[1:]):
        if after not in _TRANSITIONS[before]:
            raise CAMigrationError("migration history contains an invalid phase transition")
    if (value["phase"] == "retired") != value["retirement_confirmed"]:
        raise CAMigrationError("retirement confirmation is inconsistent with the phase")
    if value["phase"] in {"trust_distributed", "server_switched", "converged", "retired"}:
        if any(client["trust_acknowledged_at"] is None for client in clients.values()):
            raise CAMigrationError("phase claims trust distribution before all Clients acknowledged")
    if value["phase"] in {"converged", "retired"}:
        if any(client["leaf_acknowledged_at"] is None for client in clients.values()):
            raise CAMigrationError("phase claims convergence before all Clients acknowledged new leaves")
    return value


class CAMigrationStore:
    """Root-owned, atomic and versioned CA migration manifests."""

    def __init__(self, directory: str | os.PathLike[str] = "/etc/feclora/pki/migrations"):
        self.directory = _directory(directory)

    def _path(self, migration_id: str) -> str:
        try:
            normalized = str(uuid.UUID(migration_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise CAMigrationError("migration_id must be a UUID") from exc
        if normalized != migration_id:
            raise CAMigrationError("migration_id must use canonical UUID form")
        return os.path.join(self.directory, normalized + ".json")

    def _lock(self) -> int:
        fd = os.open(os.path.join(self.directory, ".lock"),
                     os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            os.close(fd)
            raise CAMigrationError("migration lock ownership or permissions are unsafe")
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _read(self, migration_id: str) -> dict[str, Any]:
        try:
            fd = os.open(self._path(migration_id), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                        or info.st_mode & 0o077 or info.st_size > MAX_MANIFEST_BYTES):
                    raise CAMigrationError("migration manifest ownership, mode or size is unsafe")
                chunks = []
                remaining = MAX_MANIFEST_BYTES + 1
                while remaining:
                    part = os.read(fd, min(65536, remaining))
                    if not part:
                        break
                    chunks.append(part)
                    remaining -= len(part)
                raw = b"".join(chunks)
            finally:
                os.close(fd)
        except OSError as exc:
            raise CAMigrationError(f"cannot safely read migration manifest: {exc}") from exc
        if len(raw) > MAX_MANIFEST_BYTES:
            raise CAMigrationError("migration manifest exceeds the size limit")
        try:
            value = json.loads(raw.decode("ascii"), object_pairs_hook=_no_duplicates)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CAMigrationError("migration manifest is not valid JSON") from exc
        return _validate(value, migration_id)

    def _write(self, value: dict[str, Any]) -> None:
        _validate(value)
        fd, temporary = tempfile.mkstemp(prefix=".migration-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(_canonical(value) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path(value["migration_id"]))
            dirfd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def create(self, old_ca_fingerprint: str, new_ca_fingerprint: str,
               client_ids: list[str], *, migration_id: str | None = None) -> dict[str, Any]:
        identifier = migration_id or str(uuid.uuid4())
        path = self._path(identifier)
        if not isinstance(client_ids, list) or len(client_ids) > 4096:
            raise CAMigrationError("client_ids must be a bounded list")
        if (any(not isinstance(item, str) or not _CLIENT_ID.fullmatch(item) for item in client_ids)
                or len(set(client_ids)) != len(client_ids)):
            raise CAMigrationError("client_ids must contain unique valid Client IDs")
        now = _now()
        value = {
            "schema_version": SCHEMA_VERSION, "migration_id": identifier,
            "created_at": now, "updated_at": now,
            "old_ca_fingerprint": old_ca_fingerprint, "new_ca_fingerprint": new_ca_fingerprint,
            "phase": "prepared",
            "clients": {item: {"trust_acknowledged_at": None, "leaf_acknowledged_at": None}
                        for item in sorted(client_ids)},
            "history": [{"phase": "prepared", "at": now}], "retirement_confirmed": False,
        }
        _validate(value)
        lock = self._lock()
        try:
            if os.path.lexists(path):
                raise CAMigrationError("migration identifier already exists")
            self._write(value)
        finally:
            os.close(lock)
        return value

    def get(self, migration_id: str) -> dict[str, Any]:
        lock = self._lock()
        try:
            return self._read(migration_id)
        finally:
            os.close(lock)

    def list(self) -> list[dict[str, Any]]:
        """Load every persisted migration for restart recovery; corruption fails closed."""
        lock = self._lock()
        try:
            names = sorted(name for name in os.listdir(self.directory)
                           if re.fullmatch(r"[0-9a-f-]{36}\\.json", name))
            if len(names) > 4096:
                raise CAMigrationError("migration inventory exceeds the supported limit")
            migrations = [self._read(name[:-5]) for name in names]
            return sorted(migrations, key=lambda item: (item["created_at"], item["migration_id"]))
        finally:
            os.close(lock)

    def _mutate(self, migration_id: str, change) -> dict[str, Any]:
        lock = self._lock()
        try:
            value = self._read(migration_id)
            change(value)
            value["updated_at"] = _now()
            _validate(value)
            self._write(value)
            return value
        finally:
            os.close(lock)

    @staticmethod
    def _advance(value: dict[str, Any], phase: str) -> None:
        if phase not in _TRANSITIONS[value["phase"]]:
            raise CAMigrationError(f"invalid migration transition: {value['phase']} -> {phase}")
        value["phase"] = phase
        value["history"].append({"phase": phase, "at": _now()})

    def begin_distribution(self, migration_id: str) -> dict[str, Any]:
        def change(value):
            if value["phase"] != "prepared":
                raise CAMigrationError("trust distribution can only begin from prepared")
            self._advance(value, "distributing")
        return self._mutate(migration_id, change)

    def acknowledge_trust(self, migration_id: str, client_id: str) -> dict[str, Any]:
        def change(value):
            if value["phase"] != "distributing" or client_id not in value["clients"]:
                raise CAMigrationError("trust acknowledgement is unexpected for this migration")
            client = value["clients"][client_id]
            client["trust_acknowledged_at"] = client["trust_acknowledged_at"] or _now()
        return self._mutate(migration_id, change)

    def complete_distribution(self, migration_id: str) -> dict[str, Any]:
        def change(value):
            if value["phase"] != "distributing":
                raise CAMigrationError("distribution is not in progress")
            if any(item["trust_acknowledged_at"] is None for item in value["clients"].values()):
                raise CAMigrationError("cannot complete distribution while Clients remain unacknowledged")
            self._advance(value, "trust_distributed")
        return self._mutate(migration_id, change)

    def record_server_switch(self, migration_id: str) -> dict[str, Any]:
        def change(value):
            if value["phase"] != "trust_distributed":
                raise CAMigrationError("Server identity can only switch after dual trust distribution")
            self._advance(value, "server_switched")
        return self._mutate(migration_id, change)

    def acknowledge_new_leaf(self, migration_id: str, client_id: str) -> dict[str, Any]:
        def change(value):
            if value["phase"] != "server_switched" or client_id not in value["clients"]:
                raise CAMigrationError("new-leaf acknowledgement is unexpected for this migration")
            client = value["clients"][client_id]
            if client["trust_acknowledged_at"] is None:
                raise CAMigrationError("Client has not acknowledged dual trust")
            client["leaf_acknowledged_at"] = client["leaf_acknowledged_at"] or _now()
        return self._mutate(migration_id, change)

    def mark_converged(self, migration_id: str) -> dict[str, Any]:
        def change(value):
            if value["phase"] != "server_switched":
                raise CAMigrationError("convergence can only follow the Server identity switch")
            if any(item["leaf_acknowledged_at"] is None for item in value["clients"].values()):
                raise CAMigrationError("cannot converge while Clients remain unacknowledged")
            self._advance(value, "converged")
        return self._mutate(migration_id, change)

    def retire_old_trust(self, migration_id: str, *, confirmed: bool) -> dict[str, Any]:
        def change(value):
            if confirmed is not True:
                raise CAMigrationError("old-trust retirement requires explicit confirmation")
            if value["phase"] != "converged":
                raise CAMigrationError("old trust cannot be retired before full convergence")
            value["retirement_confirmed"] = True
            self._advance(value, "retired")
        return self._mutate(migration_id, change)
