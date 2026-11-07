"""Durable, append-only operation journal for the Local rescue UI."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_LOG_PATH = Path("/home/feclora/logs/operations.jsonl")


class OperationLogError(RuntimeError):
    """The operation journal could not be safely persisted."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_event(path: str | os.PathLike[str], event: dict) -> None:
    """Append one fsync'd JSONL event without following symlinks."""
    destination = Path(path)
    directory = destination.parent
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode):
            raise OperationLogError("operation log directory must be a real directory")
        os.chmod(directory, 0o700)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(destination, flags, 0o600)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise OperationLogError("operation log must be a regular file")
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
    except OperationLogError:
        raise
    except OSError as exc:
        raise OperationLogError(f"cannot persist operation log: {exc}") from exc


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
    }
    append_event(log_path, {**common, "timestamp": _timestamp(), "status": "started"})
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
        append_event(log_path, {
            **common,
            "timestamp": _timestamp(),
            "status": "completed",
        })
