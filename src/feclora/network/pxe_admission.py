"""Loopback HTTP admission gate for unattended PXE boots.

MAC addresses are operational identifiers only; they are not authentication.
"""
from __future__ import annotations

import argparse
import fcntl
import http.server
import ipaddress
import json
import os
import re
import tempfile
import time
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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state_path = Path(state_path)
        self.lock_path = self.state_path.with_suffix(".lock")
        self.boot_url_prefix = self._validate_url(boot_url_prefix)
        self.boot_script_path = Path(boot_script_path)
        self.max_clients = self._positive(max_clients, "max_clients")
        self.max_duration_seconds = self._positive(max_duration_seconds, "max_duration_seconds")
        if self.max_clients is None and self.max_duration_seconds is None:
            raise PXEAdmissionError("at least one PXE admission limit is required")
        self.clock = clock
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
            return mac.lower() in state["macs"] and self._within_time_limit(state)
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

    def status(self) -> dict:
        fd = self._locked()
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            state = self._read()
            elapsed = max(0.0, self.clock() - float(state["started_at"]))
            return {
                "clients_served": len(state["macs"]),
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
