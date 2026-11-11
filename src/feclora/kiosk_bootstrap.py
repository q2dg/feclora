"""Loopback-only first-boot administrator password setup for the Feclora kiosk."""
from __future__ import annotations

import grp
import http.cookies
import os
import pwd
import secrets
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

HOST = "127.0.0.1"
PORT = 8765
COMPLETE = Path("/var/lib/feclora/kiosk-setup-complete")
ADMIN = "feclora"
ORIGIN = f"http://{HOST}:{PORT}"


class BootstrapError(RuntimeError):
    """Safe first-boot setup failure."""


def validate_password(password: str, confirmation: str) -> None:
    if not isinstance(password, str) or not isinstance(confirmation, str):
        raise BootstrapError("Enter the password twice.")
    if password != confirmation:
        raise BootstrapError("The passwords do not match.")
    if not 14 <= len(password) <= 128:
        raise BootstrapError("Use a password between 14 and 128 characters.")
    if password.strip() != password or any(ch in password for ch in ("\n", "\r", "\x00", ":")):
        raise BootstrapError("The password contains unsupported characters.")


def set_admin_password(password: str, *, runner=subprocess.run) -> None:
    if os.geteuid() != 0:
        raise BootstrapError("First-boot setup must run with system privileges.")
    try:
        account = pwd.getpwnam(ADMIN)
        wheel = grp.getgrnam("wheel")
    except KeyError as exc:
        raise BootstrapError("The administrator account is not provisioned.") from exc
    if account.pw_uid == 0 or account.pw_gid != wheel.gr_gid and ADMIN not in wheel.gr_mem:
        raise BootstrapError("The administrator account does not have the expected role.")
    try:
        result = runner(
            ["/usr/sbin/chpasswd"], input=f"{ADMIN}:{password}\n",
            text=True, capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BootstrapError("Could not set the administrator password.") from exc
    if result.returncode != 0:
        raise BootstrapError("Could not set the administrator password.")


def mark_complete(path: Path = COMPLETE) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.lstat()
    if not path.parent.is_dir() or path.parent.is_symlink() or parent.st_uid != 0:
        raise BootstrapError("First-boot state directory is not trusted.")
    if path.exists() or path.is_symlink():
        raise BootstrapError("First-boot setup has already been completed.")
    fd, temporary = tempfile.mkstemp(prefix=".kiosk-setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write("complete\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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


def build_handler(complete_path: Path = COMPLETE, password_runner=subprocess.run):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FecloraBootstrap/1"

        def _headers(self, status: int, *, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()

        def _valid_local_request(self, *, require_origin: bool) -> bool:
            if self.headers.get("Host") != f"{HOST}:{PORT}":
                return False
            if require_origin and self.headers.get("Origin") != ORIGIN:
                return False
            return True

        def do_GET(self) -> None:
            if not self._valid_local_request(require_origin=False):
                self._headers(403)
                self.wfile.write(b"Forbidden")
                return
            if complete_path.exists():
                self.send_response(303)
                self.send_header("Location", "https://localhost:9090/")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            token = secrets.token_urlsafe(32)
            self._headers(200)
            self.send_header("Set-Cookie", f"feclora_setup={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=300")
            body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Feclora initial setup</title><style>body{{font:16px system-ui,sans-serif;max-width:38rem;margin:8vh auto;padding:0 1.2rem;color:#20242a}}label{{display:block;margin:1.2rem 0 .4rem}}input{{box-sizing:border-box;width:100%;padding:.8rem;font:inherit}}button{{margin-top:1.4rem;padding:.8rem 1.2rem;font:inherit}}p{{line-height:1.5}}</style></head><body><h1>Welcome to Feclora</h1><p>Create the local administrator password to continue to Cockpit. Use at least 14 characters. This password is not stored in the browser by Feclora.</p><form method="post" action="/setup"><input type="hidden" name="token" value="{token}"><label for="password">Administrator password</label><input id="password" name="password" type="password" minlength="14" maxlength="128" autocomplete="new-password" required><label for="confirmation">Confirm password</label><input id="confirmation" name="confirmation" type="password" minlength="14" maxlength="128" autocomplete="new-password" required><button type="submit">Set password and open Cockpit</button></form></body></html>""".encode("utf-8")
            self.wfile.write(body)

        def do_POST(self) -> None:
            if not self._valid_local_request(require_origin=True) or self.path != "/setup":
                self._headers(403)
                self.wfile.write(b"Forbidden")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 1 <= length <= 4096:
                self._headers(400)
                self.wfile.write(b"Invalid request")
                return
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                token_cookie = cookie["feclora_setup"].value
            except (KeyError, http.cookies.CookieError):
                token_cookie = ""
            fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
            token = fields.get("token", [""])[0]
            password = fields.get("password", [""])[0]
            confirmation = fields.get("confirmation", [""])[0]
            if not token_cookie or not secrets.compare_digest(token_cookie, token):
                self._headers(403)
                self.wfile.write(b"Setup session expired. Reload this page.")
                return
            try:
                validate_password(password, confirmation)
                set_admin_password(password, runner=password_runner)
                mark_complete(complete_path)
            except BootstrapError as exc:
                self._headers(400)
                self.wfile.write(str(exc).encode("utf-8"))
                return
            self.send_response(303)
            self.send_header("Location", "https://localhost:9090/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", "feclora_setup=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            self.end_headers()
            self.server.setup_complete = True

        def log_message(self, fmt: str, *args) -> None:
            # Never log request bodies or credentials.
            return

    return Handler


def serve(*, complete_path: Path = COMPLETE, password_runner=subprocess.run) -> int:
    if complete_path.exists():
        return 0
    server = HTTPServer((HOST, PORT), build_handler(complete_path, password_runner))
    server.timeout = 1
    server.setup_complete = False
    try:
        while not server.setup_complete:
            server.handle_request()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
