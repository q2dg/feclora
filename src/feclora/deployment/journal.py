"""Append-only, hash-chained deployment event journal."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import stat
import threading
from datetime import datetime, timezone
from typing import Any, Mapping


class DeploymentJournalError(RuntimeError):
    """Deployment journal is unsafe, corrupt or unavailable."""


_ZERO_HASH = "0" * 64
_MAX_JOURNAL_BYTES = 32 * 1024 * 1024
_MAX_EVENT_BYTES = 64 * 1024


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DeploymentJournalError(f"duplicate journal field: {key}")
        value[key] = item
    return value


class DeploymentJournal:
    """Root/user-private append-only JSONL journal with a verifiable SHA-256 chain."""

    def __init__(self, path: str | os.PathLike[str], job_id: str) -> None:
        self.path = os.path.abspath(os.fspath(path))
        self.job_id = job_id
        self._lock = threading.RLock()
        if not isinstance(job_id, str) or not job_id:
            raise DeploymentJournalError("journal job UUID is required")
        parent = os.path.dirname(self.path)
        try:
            parent_info = os.lstat(parent)
        except OSError as exc:
            raise DeploymentJournalError(f"journal directory is unavailable: {exc}") from exc
        if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.geteuid()
                or parent_info.st_mode & 0o077):
            raise DeploymentJournalError("journal directory must be owned by the current service user with mode 0700")
        self._events = self._read_and_verify()
        if self._events and any(item.get("job_id") != job_id for item in self._events):
            raise DeploymentJournalError("journal already belongs to a different deployment job")

    @classmethod
    def inspect(cls, path: str | os.PathLike[str]) -> "DeploymentJournal":
        """Open and verify an existing journal using its first recorded job UUID."""
        absolute = os.path.abspath(os.fspath(path))
        try:
            fd = os.open(absolute, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077 or info.st_size > _MAX_JOURNAL_BYTES):
                    raise DeploymentJournalError("journal file permissions or ownership are unsafe")
                first_line = bytearray()
                while len(first_line) <= _MAX_EVENT_BYTES:
                    chunk = os.read(fd, 1)
                    if not chunk or chunk == b"\n":
                        break
                    first_line.extend(chunk)
            finally:
                os.close(fd)
        except OSError as exc:
            raise DeploymentJournalError(f"cannot inspect deployment journal: {exc}") from exc
        if not first_line or len(first_line) > _MAX_EVENT_BYTES:
            raise DeploymentJournalError("journal has no valid first event")
        try:
            first = json.loads(bytes(first_line).decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeploymentJournalError(f"journal first event is invalid: {exc}") from exc
        job_id = first.get("job_id") if isinstance(first, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise DeploymentJournalError("journal first event has no job UUID")
        return cls(absolute, job_id)
    def _read_and_verify(self) -> list[dict[str, Any]]:
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise DeploymentJournalError(f"cannot safely open journal: {exc}") from exc
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > _MAX_JOURNAL_BYTES):
                raise DeploymentJournalError("journal must be a private regular file owned by the service user")
            chunks = []
            remaining = info.st_size
            while remaining:
                part = os.read(fd, min(1024 * 1024, remaining))
                if not part:
                    raise DeploymentJournalError("journal was truncated while reading")
                chunks.append(part)
                remaining -= len(part)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
        if raw and not raw.endswith(b"\n"):
            raise DeploymentJournalError("journal ends with an incomplete event record")
        events: list[dict[str, Any]] = []
        previous = _ZERO_HASH
        for sequence, line in enumerate(raw.splitlines(), start=1):
            if not line or len(line) > _MAX_EVENT_BYTES:
                raise DeploymentJournalError("journal contains an empty or oversized event")
            try:
                event = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DeploymentJournalError(f"journal event {sequence} is invalid JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise DeploymentJournalError(f"journal event {sequence} is not an object")
            event_hash = event.pop("event_hash", None)
            if event.get("sequence") != sequence or event.get("previous_hash") != previous:
                raise DeploymentJournalError(f"journal hash chain is broken at event {sequence}")
            canonical = json.dumps(event, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True, allow_nan=False).encode("ascii")
            calculated = hashlib.sha256(canonical).hexdigest()
            if event_hash != calculated:
                raise DeploymentJournalError(f"journal event hash mismatch at event {sequence}")
            event["event_hash"] = event_hash
            previous = event_hash
            events.append(event)
        return events

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(copy.deepcopy(event) for event in self._events)

    def __call__(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            if event.get("job_id") != self.job_id:
                raise DeploymentJournalError("event belongs to a different deployment job")
            try:
                fd = os.open(
                    self.path,
                    os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    info = os.fstat(fd)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                            or info.st_mode & 0o077):
                        raise DeploymentJournalError("journal file permissions or ownership are unsafe")
                    # Another journal instance may have appended since this
                    # instance was opened. Refresh the verified chain while
                    # holding the cross-process file lock before assigning a
                    # sequence number or previous hash.
                    self._events = self._read_and_verify()
                    if any(item.get("job_id") != self.job_id for item in self._events):
                        raise DeploymentJournalError("journal already belongs to a different deployment job")
                    sequence = len(self._events) + 1
                    previous = self._events[-1]["event_hash"] if self._events else _ZERO_HASH
                    record = dict(event)
                    record["sequence"] = sequence
                    record["previous_hash"] = previous
                    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=True, allow_nan=False).encode("ascii")
                    event_hash = hashlib.sha256(canonical).hexdigest()
                    record["event_hash"] = event_hash
                    line = json.dumps(record, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, allow_nan=False).encode("ascii") + b"\\n"
                    if len(line) > _MAX_EVENT_BYTES:
                        raise DeploymentJournalError("deployment journal event exceeds the size limit")
                    if info.st_size + len(line) > _MAX_JOURNAL_BYTES:
                        raise DeploymentJournalError("deployment journal reached its 32 MiB safety limit")
                    written = 0
                    while written < len(line):
                        count = os.write(fd, line[written:])
                        if count <= 0:
                            raise OSError("journal append made no forward progress")
                        written += count
                    os.fsync(fd)
                    self._events.append(record)
                finally:
                    os.close(fd)
                parent_fd = os.open(os.path.dirname(self.path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except OSError as exc:
                raise DeploymentJournalError(f"cannot persist deployment event: {exc}") from exc

    def recovery_report(self) -> dict[str, Any]:
        """Reconstruct an audit-only recovery summary; never recreate live sessions."""
        with self._lock:
            events = tuple(copy.deepcopy(event) for event in self._events)
        if not events:
            raise DeploymentJournalError("cannot recover an empty deployment journal")
        first = events[0]
        job = first.get("job")
        if first.get("event") != "job_created" or not isinstance(job, dict):
            raise DeploymentJournalError("journal does not begin with a valid job_created event")
        clients: dict[str, dict[str, Any]] = {}
        for event in events:
            mac = event.get("client_mac")
            if mac is None:
                continue
            if not isinstance(mac, str) or not mac:
                raise DeploymentJournalError("journal contains an invalid client identity")
            state = event.get("client_state")
            if state is not None:
                if state not in {"connected", "ready", "running", "succeeded", "failed", "disconnected"}:
                    raise DeploymentJournalError("journal contains an unknown client state")
                clients[mac] = {
                    "state": state,
                    "detail": event.get("detail"),
                    "last_event": event.get("event"),
                    "timestamp": event.get("timestamp"),
                }
        job_state = events[-1].get("job_state")
        if job_state not in {"created", "armed", "running", "completed", "failed", "cancelled"}:
            raise DeploymentJournalError("journal contains an unknown job state")
        operator_reconciled = events[-1].get("event") == "operator_reconciled"
        has_service_start = any(event.get("event") == "service_started" for event in events)
        clean_unarmed_stop = (
            events[-1].get("event") == "service_stopped"
            and job_state == "created" and not clients
        )
        interrupted = (
            job_state in {"armed", "running"}
            or (job_state == "created" and bool(clients))
            or (job_state == "created" and has_service_start and not clean_unarmed_stop)
        )
        if operator_reconciled and job_state != "failed":
            raise DeploymentJournalError("operator reconciliation must close the interrupted job as failed")
        return {
            "job_id": self.job_id,
            "job": dict(job),
            "job_state": job_state,
            "clients": clients,
            "event_count": len(events),
            "last_event": events[-1].get("event"),
            "interrupted": interrupted,
            "operator_reconciled": operator_reconciled,
            "automatic_resume": False,
            "recommendation": (
                "Inspect every client and destination disk, then create a new job; "
                "Feclora never resumes destructive writes after a crash."
                if interrupted else
                ("Operator inspected/reconciled this interrupted job; it remains failed and no operation was resumed."
                 if operator_reconciled else
                 "Audit-only terminal record; no session or device operation is resumed.")
            ),
        }

    def reconcile_after_operator_inspection(self, confirmation: str) -> dict[str, Any]:
        """Durably close an interrupted record after an operator inspected every target.

        This is an audit/reconciliation action only: it does not resume, retry,
        roll back, or otherwise touch a block device.
        """
        report = self.recovery_report()
        expected = f"RECONCILE {self.job_id}"
        if confirmation != expected:
            raise DeploymentJournalError("operator reconciliation confirmation does not match")
        if not report["interrupted"]:
            raise DeploymentJournalError("deployment journal is not awaiting recovery reconciliation")
        self({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": self.job_id,
            "event": "operator_reconciled",
            "job_state": "failed",
            "detail": "Operator confirmed manual inspection of every client and destination; no automatic resume performed.",
        })
        return self.recovery_report()

    def latest_state(self) -> dict[str, Any] | None:
        """Return the most recent recorded job/client state without resuming a job."""
        with self._lock:
            return copy.deepcopy(self._events[-1]) if self._events else None
