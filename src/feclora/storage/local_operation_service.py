"""Root-owned worker for durable local storage operations."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import signal
from pathlib import Path
from typing import Any

from feclora.storage.local_operations import (
    LocalOperationError, LocalOperationStore, TERMINAL_STATES,
)

RUNTIME = Path("/run/feclora")
DEVICE_LOCKS = RUNTIME / "local-operation-locks"


class LocalOperationCancelled(Exception):
    """Raised by the worker after systemd requests an orderly stop."""


def _cancel_on_sigterm(_signum: int, _frame: Any) -> None:
    raise LocalOperationCancelled("cancellation requested by operator")


class _ProgressForwarder:
    """Consume the existing operation engine's NDJSON and persist safe progress."""

    def __init__(self, store: LocalOperationStore, operation_id: str) -> None:
        self.store = store
        self.operation_id = operation_id
        self.buffer = ""

    def write(self, value: str) -> int:
        self.buffer += value
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._line(line)
        return len(value)

    def flush(self) -> None:
        if self.buffer:
            self._line(self.buffer)
            self.buffer = ""

    def _line(self, line: str) -> None:
        if not line or len(line) > 16 * 1024:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict) or event.get("event") != "progress":
            return
        details: dict[str, Any] = {}
        for key in ("bytes_done", "bytes_total"):
            value = event.get(key)
            if value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
                details[key] = value
        if isinstance(event.get("message"), str):
            details["message"] = event["message"][:256]
        self.store.append(self.operation_id, "progress", details)


def _device_lock_fds(params: dict[str, Any]) -> list[int]:
    """Lock physical block-device identities, not just potentially aliased paths."""
    devices = sorted({value for key, value in params.items()
                      if key in {"source", "target"} and isinstance(value, str)})
    RUNTIME.mkdir(mode=0o755, parents=True, exist_ok=True)
    runtime_info = os.lstat(RUNTIME)
    if (not stat.S_ISDIR(runtime_info.st_mode) or stat.S_ISLNK(runtime_info.st_mode)
            or runtime_info.st_uid != 0 or runtime_info.st_mode & 0o022):
        raise LocalOperationError("Feclora runtime directory is unsafe")
    DEVICE_LOCKS.mkdir(mode=0o700, exist_ok=True)
    directory_info = os.lstat(DEVICE_LOCKS)
    if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
            or directory_info.st_uid != 0 or directory_info.st_mode & 0o077):
        raise LocalOperationError("device lock directory is unsafe")
    os.chmod(DEVICE_LOCKS, 0o700)
    identities: dict[tuple[int, int], str] = {}
    for device in devices:
        try:
            info = os.stat(device)
        except OSError as exc:
            raise LocalOperationError(f"cannot resolve block device {device}: {exc}") from exc
        if not stat.S_ISBLK(info.st_mode):
            raise LocalOperationError(f"{device} is not a block device")
        identities[(os.major(info.st_rdev), os.minor(info.st_rdev))] = device
    fds: list[int] = []
    try:
        for major_minor, device in sorted(identities.items()):
            identity = f"{major_minor[0]}:{major_minor[1]}"
            digest = hashlib.sha256(identity.encode("ascii")).hexdigest()
            path = DEVICE_LOCKS / (digest + ".lock")
            fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
                os.close(fd)
                raise LocalOperationError("device lock file is unsafe")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                os.close(fd)
                raise LocalOperationError(f"device {device} is already in use by another Feclora operation") from exc
            fds.append(fd)
        # Re-resolve after acquiring locks to close a device-node replacement race.
        for major_minor, device in identities.items():
            info = os.stat(device)
            if (not stat.S_ISBLK(info.st_mode)
                    or (os.major(info.st_rdev), os.minor(info.st_rdev)) != major_minor):
                raise LocalOperationError(f"block device identity changed while locking {device}")
        return fds
    except Exception:
        for fd in reversed(fds):
            os.close(fd)
        raise


def execute(operation_id: str) -> int:
    if os.geteuid() != 0:
        raise LocalOperationError("local storage worker must run as root")
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _cancel_on_sigterm)
    store = LocalOperationStore()
    definition = store.definition(operation_id)
    status = store.status(operation_id)
    if status["state"] != "queued":
        raise LocalOperationError("only a queued operation can be started")
    fds: list[int] = []
    try:
        store.append(operation_id, "preflight", {"message": "Validating operation definition and device locks"})
        # Reuse the existing host-wide Server/Client/storage exclusion lock.
        from feclora.webapi import _execute_operation, _storage_operation_lock
        with _storage_operation_lock():
            fds = _device_lock_fds(definition["params"])
            # The engine revalidates device paths, repository identity,
            # destructive typed confirmation and image security immediately
            # before it performs storage I/O.
            store.append(operation_id, "running", {"action": definition["action"]})
            forwarder = _ProgressForwarder(store, operation_id)
            with contextlib.redirect_stdout(forwarder):
                result = _execute_operation(
                    definition["action"], definition["params"], operation_id,
                )
                forwarder.flush()
            store.append(operation_id, "verifying", {"message": "Storage engine returned successfully"})
            safe_result = {
                key: value for key, value in result.items()
                if key in {"image_id", "image_type", "source_image_id", "target",
                           "source", "bytes_copied", "verified", "signed", "encrypted"}
                and isinstance(value, (str, int, bool, type(None)))
            }
            if definition["action"] == "sftp_inventory":
                manifests = result.get("manifests")
                if (isinstance(manifests, list) and len(manifests) <= 1000
                        and all(isinstance(name, str) and re.fullmatch(
                            r"(?:manifest\\.json|[A-Za-z0-9][A-Za-z0-9._-]{0,127}\\.manifest\\.json)", name
                        ) for name in manifests)):
                    safe_result["manifests"] = manifests
            store.append(operation_id, "completed", safe_result)
        return 0
    except LocalOperationCancelled:
        current = store.status(operation_id)["state"]
        if current not in TERMINAL_STATES:
            destructive = definition["action"].startswith(("restore_", "clone_"))
            store.append(operation_id, "cancelled", {
                "reason": "operator requested cancellation; worker and child processes were stopped",
                "destination_may_be_partial": bool(destructive and current == "running"),
            })
        # A controlled cancellation is a normal terminal outcome for systemd,
        # not a failed service invocation. ExecStopPost remains idempotent.
        return 0
    except BaseException as exc:
        try:
            current = store.status(operation_id)["state"]
            if current not in TERMINAL_STATES:
                store.append(operation_id, "failed", {
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:512],
                })
        except Exception:
            pass
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        for fd in reversed(fds):
            os.close(fd)


def mark_interrupted(operation_id: str) -> int:
    if os.geteuid() != 0:
        raise LocalOperationError("local storage recovery must run as root")
    store = LocalOperationStore()
    store.mark_interrupted(operation_id)
    return 0


def recover_interrupted() -> int:
    if os.geteuid() != 0:
        raise LocalOperationError("local operation recovery must run as root")
    store = LocalOperationStore()
    recovered = 0
    inspection_errors = 0
    for operation_id in store.operation_ids():
        try:
            report = store.status(operation_id)
            if report["state"] not in TERMINAL_STATES:
                store.mark_interrupted(operation_id)
                recovered += 1
        except Exception as exc:
            # One damaged journal must not prevent recovery of unrelated jobs.
            print(
                f"Cannot reconcile local operation {operation_id}: {str(exc)[:256]}",
                file=sys.stderr,
            )
            inspection_errors += 1
    print(
        f"Marked {recovered} unfinished local operation(s) interrupted; "
        f"{inspection_errors} operation(s) need manual journal inspection. "
        "No operation was resumed."
    )
    return 1 if inspection_errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feclora durable local storage worker")
    parser.add_argument("--operation-id")
    parser.add_argument("--mark-interrupted", action="store_true")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args(argv)
    if args.recover and (args.operation_id or args.mark_interrupted):
        parser.error("--recover cannot be combined with --operation-id or --mark-interrupted")
    if not args.recover and not args.operation_id:
        parser.error("--operation-id is required unless --recover is selected")
    try:
        if args.recover:
            return recover_interrupted()
        return mark_interrupted(args.operation_id) if args.mark_interrupted else execute(args.operation_id)
    except Exception as exc:
        print(f"feclora local operation: {str(exc)[:512]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
