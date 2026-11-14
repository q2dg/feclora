"""Loopback HTTP admission gate for unattended PXE boots.

The admission ledger counts reported MAC addresses for operational selection and limits.
"""
from __future__ import annotations

import argparse
import fcntl
import http.server
import ipaddress
import json
import os
import re
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class PXEAdmissionError(RuntimeError):
    """The PXE admission ledger is invalid or unavailable."""


class PXEAdmission:
    def __init__(
        self,
        state_path: str,
        *,
        boot_url_prefix: str,
        boot_script_path: str,
        max_clients: int | None,
        max_duration_seconds: int | None,
        clock: Callable[[], float] = time.monotonic,
        http_root: str = "/srv/feclora/http",
        report_log_path: str = "/var/lib/feclora/pxe/remote-reports.jsonl",
    ) -> None:
        self.state_path = Path(state_path)
        self.lock_path = self.state_path.with_suffix(".lock")
        self.boot_url_prefix = self._validate_url(boot_url_prefix)
        self.boot_script_path = Path(boot_script_path)
        self.max_clients = self._positive(max_clients, "max_clients")
        self.max_duration_seconds = self._positive(max_duration_seconds, "max_duration_seconds")
        self.clock = clock
        self.http_root = Path(http_root)
        self.report_log_path = Path(report_log_path)
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state_path.parent.is_symlink() or not self.state_path.parent.is_dir():
            raise PXEAdmissionError("PXE admission state directory must be a real directory")
        self._initialize()

    @staticmethod
    def _positive(value: int | None, label: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PXEAdmissionError(f"{label} must be a positive integer or null")
        return value

    @staticmethod
    def _validate_url(value: str) -> str:
        try:
            parsed = urlsplit(value)
            address = ipaddress.ip_address(parsed.hostname or "")
            port = parsed.port
        except (ValueError, TypeError) as exc:
            raise PXEAdmissionError("PXE boot URL prefix must be an HTTP IPv4 URL") from exc
        if (parsed.scheme != "http" or address.version != 4 or address.is_unspecified
                or address.is_loopback or address.is_multicast or port is None
                or parsed.path != "/pxe/boot/" or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            raise PXEAdmissionError("PXE boot URL prefix is invalid")
        return value

    def _locked(self) -> int:
        return os.open(self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)

    def _initialize(self) -> None:
        fd = self._locked()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                self.state_path.lstat()
            except FileNotFoundError:
                self._write({"schema_version": 1, "started_at": self.clock(), "macs": []})
            else:
                self._read()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self) -> dict:
        try:
            info = self.state_path.lstat()
        except FileNotFoundError:
            return {"schema_version": 1, "started_at": self.clock(), "macs": []}
        if (not self.state_path.is_file() or self.state_path.is_symlink()
                or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 65536):
            raise PXEAdmissionError("PXE admission state file is unsafe")
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PXEAdmissionError("PXE admission state file is unreadable") from exc
        if (not isinstance(state, dict) or set(state) != {"schema_version", "started_at", "macs"}
                or state["schema_version"] != 1 or isinstance(state["started_at"], bool)
                or not isinstance(state["started_at"], (int, float))
                or not isinstance(state["macs"], list) or len(state["macs"]) > 4096
                or any(not isinstance(mac, str) or not _MAC_RE.fullmatch(mac) for mac in state["macs"])
                or len(set(state["macs"])) != len(state["macs"])):
            raise PXEAdmissionError("PXE admission state file has an invalid schema")
        return state

    def _write(self, state: dict) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".admission.", dir=self.state_path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
            directory_fd = os.open(self.state_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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

    def _within_time_limit(self, state: dict) -> bool:
        elapsed = max(0.0, self.clock() - float(state["started_at"]))
        return self.max_duration_seconds is None or elapsed < self.max_duration_seconds

    def admit(self, mac: str) -> tuple[bool, str]:
        if not isinstance(mac, str) or not _MAC_RE.fullmatch(mac):
            return False, "invalid client MAC address"
        normalized = mac.lower()
        fd = self._locked()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            state = self._read()
            if not self._within_time_limit(state):
                return False, "PXE serving time limit has elapsed"
            known = normalized in state["macs"]
            if not known and self.max_clients is not None and len(state["macs"]) >= self.max_clients:
                return False, "PXE client limit has been reached"
            if not known:
                state["macs"].append(normalized)
                self._write(state)
            return True, "already registered" if known else "registered"
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def is_admitted(self, mac: str) -> bool:
        if not isinstance(mac, str) or not _MAC_RE.fullmatch(mac):
            return False
        fd = self._locked()
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            state = self._read()
            return self._within_time_limit(state) and mac.lower() in state["macs"]
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def boot_script(self) -> bytes:
        try:
            info = self.boot_script_path.lstat()
        except OSError as exc:
            raise PXEAdmissionError(f"unattended PXE boot script is unavailable: {exc}") from exc
        if (not self.boot_script_path.is_file() or self.boot_script_path.is_symlink()
                or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > 8192):
            raise PXEAdmissionError("unattended PXE boot script is unsafe")
        try:
            return self.boot_script_path.read_bytes()
        except OSError as exc:
            raise PXEAdmissionError(f"cannot read unattended PXE boot script: {exc}") from exc

    def record_report(self, job_id: str, mac: str, event: dict) -> bool:
        """Persist one bounded client-asserted event; return False for duplicates."""
        try:
            canonical = str(uuid.UUID(job_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise PXEAdmissionError("report job ID must be a UUID") from exc
        if canonical != job_id or not self.is_admitted(mac):
            raise PXEAdmissionError("PXE client is not admitted for this report")
        answer = self.http_root / "answers" / canonical / "answer.json"
        try:
            info = answer.lstat()
        except OSError as exc:
            raise PXEAdmissionError("reported PXE answer job is not currently published") from exc
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022
                or info.st_size > 65536):
            raise PXEAdmissionError("published PXE answer is unsafe")
        allowed = {"event_id", "operation_id", "operation", "timestamp", "status",
                   "target", "image_id", "bytes_done", "bytes_total", "error_type", "error"}
        if not isinstance(event, dict) or set(event) - allowed or not {
            "event_id", "operation_id", "operation", "timestamp", "status",
            "target", "image_id"
        }.issubset(event):
            raise PXEAdmissionError("PXE report event has an invalid schema")
        try:
            event_id = str(uuid.UUID(event["event_id"]))
            operation_id = str(uuid.UUID(event["operation_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise PXEAdmissionError("PXE report event identifiers must be UUIDs") from exc
        if event_id != event["event_id"] or operation_id != event["operation_id"]:
            raise PXEAdmissionError("PXE report event identifiers must be canonical UUIDs")
        if (event["operation"] != "restore_disk"
                or not isinstance(event["status"], str)
                or event["status"] not in {"started", "progress", "completed", "failed", "cancelled"}
                or not isinstance(event["timestamp"], str) or len(event["timestamp"]) > 40
                or not isinstance(event["target"], str) or len(event["target"]) > 256
                or not isinstance(event["image_id"], str) or len(event["image_id"]) > 128):
            raise PXEAdmissionError("PXE report event fields are invalid")
        for key in ("bytes_done", "bytes_total"):
            value = event.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or value < 0 or value > 2**63 - 1):
                raise PXEAdmissionError(key + " must be a non-negative integer or null")
        for key in ("error_type", "error"):
            value = event.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 512):
                raise PXEAdmissionError(key + " must be text under 513 characters")
        path = self.report_log_path
        directory = path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_info = directory.lstat()
        if (not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode)
                or directory_info.st_uid != os.geteuid() or directory_info.st_mode & 0o077):
            raise PXEAdmissionError("PXE report journal directory is unsafe")
        lock_path = path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                existing = path.lstat()
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if (not stat.S_ISREG(existing.st_mode) or stat.S_ISLNK(existing.st_mode)
                        or existing.st_uid != os.geteuid() or existing.st_mode & 0o077
                        or existing.st_size > 8 * 1024 * 1024):
                    raise PXEAdmissionError("PXE report journal is unsafe or exceeds 8 MiB")
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            previous = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(previous, dict) and previous.get("event_id") == event_id:
                            return False
            record = {
                **event, "event_id": event_id, "operation_id": operation_id,
                "job_id": canonical, "client_mac": mac.lower(),
                "received_at": time.time(),
            }
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                    raise PXEAdmissionError("PXE report journal file is unsafe")
                os.fchmod(fd, 0o600)
                payload = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
                view = memoryview(payload)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        raise PXEAdmissionError("short write to PXE report journal")
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            return True
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def status(self) -> dict:
        fd = self._locked()
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            state = self._read()
            elapsed = max(0.0, self.clock() - float(state["started_at"]))
            return {
                "clients_served": len(state["macs"]) if self.max_clients is not None else None,
                "max_clients": self.max_clients,
                "elapsed_seconds": int(elapsed),
                "max_duration_seconds": self.max_duration_seconds,
                "accepting": self._within_time_limit(state) and (
                    self.max_clients is None or len(state["macs"]) < self.max_clients
                ),
            }
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


class _Handler(http.server.BaseHTTPRequestHandler):
    admission: PXEAdmission
    server_version = "FecloraPXEAdmission/1"

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        prefix, _, job_id = path.rpartition("/")
        if prefix != "/pxe/report":
            self._reply(404, b"not found\n")
            return
        declared = self.headers.get("Content-Length")
        try:
            length = int(declared) if declared is not None else -1
        except ValueError:
            length = -1
        if length < 1 or length > 16384:
            self._reply(413, b"invalid report size\n")
            return
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict) or set(value) != {"client_mac", "event"}:
                raise PXEAdmissionError("report body must contain client_mac and event")
            if not isinstance(value["client_mac"], str) or not _MAC_RE.fullmatch(value["client_mac"]):
                raise PXEAdmissionError("report client MAC is invalid")
            created = self.admission.record_report(job_id, value["client_mac"], value["event"])
        except (UnicodeError, json.JSONDecodeError, PXEAdmissionError, OSError) as exc:
            self._reply(400, (str(exc)[:512] + "\n").encode("utf-8"))
            return
        self._reply(200, b"recorded\n" if created else b"duplicate\n")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        prefix, _, mac = path.rpartition("/")
        if prefix == "/pxe/admit":
            allowed, reason = self.admission.admit(mac)
            if not allowed:
                body = ("#!ipxe\necho PXE admission denied: " + reason.replace("\n", " ") + "\n").encode()
                self._reply(403, body)
                return
            body = ("#!ipxe\nchain " + self.admission.boot_url_prefix + mac.lower() + "\n").encode()
            self._reply(200, body)
            return
        if prefix == "/pxe/boot":
            if not self.admission.is_admitted(mac):
                self._reply(403, b"PXE client is not admitted or the serving window has closed\n")
                return
            try:
                body = self.admission.boot_script()
            except PXEAdmissionError:
                self._reply(503, b"PXE unattended boot script is unavailable\n")
                return
            self._reply(200, body)
            return
        self._reply(404, b"not found\n")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--boot-url-prefix", required=True)
    parser.add_argument("--boot-script", required=True)
    parser.add_argument("--max-clients", type=int)
    parser.add_argument("--max-duration-seconds", type=int)
    args = parser.parse_args()
    if args.bind != "127.0.0.1" or not 1 <= args.port <= 65535:
        parser.error("admission service must bind to loopback and a valid TCP port")
    admission = PXEAdmission(
        args.state, boot_url_prefix=args.boot_url_prefix,
        boot_script_path=args.boot_script,
        max_clients=args.max_clients,
        max_duration_seconds=args.max_duration_seconds,
    )
    handler = type("PXEAdmissionHandler", (_Handler,), {"admission": admission})
    server = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
