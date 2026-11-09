"""Durable, append-only operation journal for the Local rescue UI."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_LOG_PATH = Path("/home/feclora/logs/operations.jsonl")


class OperationLogError(RuntimeError):
    """The operation journal could not be safely persisted."""


def _process_start_ticks(stat_path: str | os.PathLike[str]) -> int | None:
    try:
        raw = Path(stat_path).read_text(encoding="ascii")
        fields = raw[raw.rfind(")") + 2:].split()
        return int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def _operation_process_active(event: dict) -> bool:
    """Return whether the exact process that started an operation still exists."""
    pid = event.get("pid")
    boot_id = event.get("boot_id")
    start_ticks = event.get("process_start_ticks")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(boot_id, str):
        # Older journal entries have no process identity; they need manual review.
        return False
    try:
        current_boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        # If process identity cannot be checked, do not falsely report a live
        # destructive operation as interrupted.
        return True
    if current_boot_id != boot_id:
        return False
    if not isinstance(start_ticks, int):
        return True
    current_ticks = _process_start_ticks(f"/proc/{pid}/stat")
    if current_ticks is None:
        return Path(f"/proc/{pid}").exists()
    return current_ticks == start_ticks


def reconcile_interrupted(events: list[dict]) -> list[dict]:
    """Mark unclosed operations interrupted when their originating process exited.

    This is an in-memory view only: it never edits the journal or retries disk I/O.
    """
    terminal_ids = {
        event.get("operation_id") for event in events
        if event.get("status") in {"completed", "failed", "cancelled"}
    }
    result = []
    for event in events:
        if (event.get("status") == "started"
                and event.get("operation_id") not in terminal_ids
                and not _operation_process_active(event)):
            result.append({
                **event,
                "status": "interrupted",
                "recovery_note": "The originating process exited before a terminal event. Inspect the destination; the operation was not resumed.",
            })
        else:
            result.append(event)
    return result


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_event(path: str | os.PathLike[str], event: dict) -> None:
    """Append one fsync'd JSONL event without following symlinks.

    The log file is opened relative to a pinned directory descriptor. Both the
    file contents and the directory entry are synced before returning, so a
    newly created journal survives a normal filesystem crash-consistency
    boundary. Advisory locking keeps concurrent UI/process writers serialized.
    """
    destination = Path(path)
    directory = destination.parent
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(directory, directory_flags)
        try:
            directory_info = os.fstat(directory_fd)
            if not stat.S_ISDIR(directory_info.st_mode):
                raise OperationLogError("operation log directory must be a real directory")
            if directory_info.st_uid != os.geteuid():
                raise OperationLogError("operation log directory must be owned by the current user")
            os.fchmod(directory_fd, 0o700)

            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(destination.name, flags, 0o600, dir_fd=directory_fd)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode):
                    raise OperationLogError("operation log must be a regular file")
                if metadata.st_uid != os.geteuid():
                    raise OperationLogError("operation log must be owned by the current user")
                os.fchmod(fd, 0o600)
                payload = (json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
                fcntl.flock(fd, fcntl.LOCK_EX)
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OperationLogError("short write while appending operation log")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            # Persist creation of the log entry as well as its contents.
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OperationLogError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise OperationLogError(f"cannot persist operation log: {exc}") from exc

_ACTIVE_OPERATION: ContextVar[dict | None] = ContextVar("feclora_active_operation", default=None)
_PROGRESS_INTERVAL_SECONDS = 30.0
_PROGRESS_INTERVAL_BYTES = 1024 * 1024 * 1024


def record_progress(bytes_done: int, bytes_total: int | None) -> None:
    """Persist throttled progress for the operation active in this context."""
    active = _ACTIVE_OPERATION.get()
    if active is None:
        return
    done = max(0, int(bytes_done))
    total = max(0, int(bytes_total)) if bytes_total is not None else None
    now = __import__("time").monotonic()
    last_done = active["last_bytes"]
    is_first = last_done is None
    is_final = total is not None and done >= total
    if not (is_first or is_final or done - last_done >= _PROGRESS_INTERVAL_BYTES
            or now - active["last_at"] >= _PROGRESS_INTERVAL_SECONDS):
        return
    append_event(active["log_path"], {
        **active["common"],
        "timestamp": _timestamp(),
        "status": "progress",
        "bytes_done": done,
        "bytes_total": total,
    })
    active["last_bytes"] = done
    active["last_at"] = now



@contextmanager
def operation_record(
    operation: str,
    target: str,
    *,
    image_id: str | None = None,
    log_path: str | os.PathLike[str] = DEFAULT_LOG_PATH,
) -> Iterator[str]:
    """Record started and terminal events; refuse to start if journaling fails."""
    operation_id = str(uuid.uuid4())
    common = {
        "operation_id": operation_id,
        "operation": operation,
        "target": target,
        "image_id": image_id,
        "pid": os.getpid(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
        "process_start_ticks": _process_start_ticks("/proc/self/stat"),
    }
    append_event(log_path, {**common, "timestamp": _timestamp(), "status": "started"})
    import time
    token = _ACTIVE_OPERATION.set({
        "common": common,
        "log_path": log_path,
        "last_bytes": None,
        "last_at": time.monotonic(),
    })
    try:
        try:
            yield operation_id
        except BaseException as exc:
            status = "cancelled" if "cancel" in type(exc).__name__.lower() else "failed"
            try:
                append_event(log_path, {
                    **common,
                    "timestamp": _timestamp(),
                    "status": status,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                })
            except OperationLogError as log_exc:
                raise OperationLogError(
                    f"{status} operation and its terminal event could not be logged: {log_exc}"
                ) from exc
            raise
        else:
            try:
                append_event(log_path, {
                    **common,
                    "timestamp": _timestamp(),
                    "status": "completed",
                })
            except OperationLogError as exc:
                raise OperationLogError(
                    f"operation completed but its terminal journal event could not be persisted: {exc}"
                ) from exc
    finally:
        _ACTIVE_OPERATION.reset(token)
