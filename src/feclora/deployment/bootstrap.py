"""First-run Server deployment PKI and configuration bootstrap."""
from __future__ import annotations

import ipaddress
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from feclora.deployment.managed_pki import PKIError, initialize_server_pki


class BootstrapError(RuntimeError):
    """Server deployment bootstrap failed safely."""


def _ensure_directory(path: str, mode: int = 0o700) -> str:
    os.makedirs(path, mode=mode, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise BootstrapError(f"{path} must be a real root-owned directory")
    os.chmod(path, mode)
    return path


def _write_json(path: str, value: dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".deployment-server.", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        dirfd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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


def ensure_server_deployment_config(
    bind_address: str,
    *,
    config_path: str = "/etc/feclora/deployment-server.json",
    pki_directory: str = "/etc/feclora/pki",
    repository: str = "/var/lib/feclora/images",
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
    minisign: str = "/usr/bin/minisign",
) -> bool:
    """Create secure default TLS and image-signing material on first Server use.

    Existing operator-managed configuration is never rewritten. Returns True
    only when a new default configuration was created.
    """
    if os.geteuid() != 0:
        raise BootstrapError("Server deployment bootstrap requires root")
    try:
        address = ipaddress.ip_address(bind_address)
    except ValueError as exc:
        raise BootstrapError("Server bind address must be a concrete IPv4 address") from exc
    if address.version != 4 or address.is_unspecified or address.is_multicast:
        raise BootstrapError("Server bind address must be a concrete unicast IPv4 address")
    config_directory = _ensure_directory(os.path.dirname(config_path), 0o700)
    if os.path.lexists(config_path):
        info = os.lstat(config_path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise BootstrapError("existing Server deployment config must be root-owned mode 0600")
        return False
    pki = initialize_server_pki(pki_directory, runner=runner, openssl=openssl)
    age_identity = os.path.join(pki_directory, "server.age")
    age_recipients = os.path.join(pki_directory, "age-recipients.txt")
    if not os.path.exists(age_identity):
        execute = runner or subprocess.run
        try:
            result = execute(["/usr/bin/age-keygen", "-o", age_identity], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=60)
            if result.returncode != 0:
                raise BootstrapError("age-keygen failed while creating Server recipient identity")
            public = execute(["/usr/bin/age-keygen", "-y", age_identity], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=30)
            if public.returncode != 0 or not public.stdout.strip().startswith("age1"):
                raise BootstrapError("age-keygen did not return a valid Server recipient")
            Path(age_recipients).write_text(public.stdout.strip() + "\\n", encoding="ascii")
            os.chmod(age_identity, 0o600)
            os.chmod(age_recipients, 0o600)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BootstrapError(f"could not create Server age identity: {exc}") from exc
    elif not os.path.isfile(age_recipients):
        raise BootstrapError("Server age identity exists but its recipient inventory is missing; refusing to regenerate trust material")
    signing_secret = os.path.join(pki_directory, "server.minisign.key")
    signing_public = os.path.join(pki_directory, "server.pub")
    if os.path.exists(signing_secret) != os.path.exists(signing_public):
        raise BootstrapError("partial minisign keypair exists; refusing to overwrite it")
    if not os.path.exists(signing_secret):
        execute = runner or subprocess.run
        try:
            result = execute(
                [minisign, "-G", "-s", signing_secret, "-p", signing_public, "-W"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                check=False, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BootstrapError(f"could not generate Server image-signing key: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:512]
            raise BootstrapError("minisign key generation failed" + (f": {detail}" if detail else ""))
        os.chmod(signing_secret, 0o600)
        os.chmod(signing_public, 0o644)
    for path in (signing_secret, signing_public):
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise BootstrapError("Server minisign key files must be root-owned regular files")
    if os.stat(signing_secret).st_mode & 0o077:
        raise BootstrapError("Server minisign secret key must be mode 0600 or stricter")
    _ensure_directory(repository, 0o700)
    config = {
        "schema_version": 1,
        "bind_address": str(address),
        "port": 9443,
        "local_identity": "URI:feclora-server",
        "ca_file": pki["ca_file"],
        "certificate_file": pki["server_certificate"],
        "private_key_file": pki["server_key"],
        "client_identity_to_mac": {},
        "client_minisign_public_keys": {},
        "server_minisign_public_key": signing_public,
        "repository": repository,
    }
    _write_json(config_path, config)
    return True
