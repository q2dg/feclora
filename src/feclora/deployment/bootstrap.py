"""First-run Server deployment PKI and configuration bootstrap."""
from __future__ import annotations

import ipaddress
import json
import os
import stat
import shutil
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
) -> bool:
    """Create TLS configuration and optional age encryption material.

    Existing operator-managed configuration is never rewritten.
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
    # Age encryption is optional; TLS/PKI bootstrap does not depend on it.
    age_identity = os.path.join(pki_directory, "server.age")
    age_recipients = os.path.join(pki_directory, "age-recipients.txt")
    age_keygen = shutil.which("age-keygen")
    if not os.path.exists(age_identity):
        if os.path.lexists(age_recipients):
            raise BootstrapError("Server age recipient inventory exists without its identity; refusing to overwrite it")
        if age_keygen:
            execute = runner or subprocess.run
            try:
                result = execute([age_keygen, "-o", age_identity], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=60)
                if result.returncode != 0:
                    raise BootstrapError("age-keygen failed while creating optional Server recipient identity")
                public = execute([age_keygen, "-y", age_identity], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=30)
                if public.returncode != 0 or not public.stdout.strip().startswith("age1"):
                    raise BootstrapError("age-keygen did not return a valid Server recipient")
                Path(age_recipients).write_text(public.stdout.strip() + "\n", encoding="ascii")
                os.chmod(age_identity, 0o600)
                os.chmod(age_recipients, 0o600)
            except (OSError, subprocess.SubprocessError) as exc:
                raise BootstrapError(f"could not create optional Server age identity: {exc}") from exc
    else:
        info = os.lstat(age_identity)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise BootstrapError("Server age identity must be root-owned and mode 0600")
        if not os.path.isfile(age_recipients):
            raise BootstrapError("Server age identity exists but its recipient inventory is missing; refusing to regenerate trust material")
        recipients_info = os.lstat(age_recipients)
        if not stat.S_ISREG(recipients_info.st_mode) or recipients_info.st_uid != 0 or recipients_info.st_mode & 0o077:
            raise BootstrapError("Server age recipient inventory must be root-owned and private")

    _ensure_directory(repository, 0o700)
    config = {
        "schema_version": 1,
        "bind_address": str(address),
        "port": 9443,
        "local_identity": "URI:feclora-server",
        "ca_file": pki["ca_file"],
        "certificate_file": pki["server_certificate"],
        "private_key_file": pki["server_key"],
        "repository": repository,
    }
    _write_json(config_path, config)
    return True
