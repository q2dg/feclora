"""Root-only Server-side certificate enrollment and revocation helpers.

Private keys are never generated, imported, or transmitted by this module.
An operator provisions certificates through an external CA and imports only
the public Client certificate plus its optional minisign public key.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from typing import Any

from feclora.deployment.runtime_config import (
    load_server_runtime_config,
)


class EnrollmentError(RuntimeError):
    """Client certificate enrollment or revocation failed."""


_MAC = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def _secure_regular_file(path: str, label: str) -> None:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise EnrollmentError(f"{label} path must be absolute")
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise EnrollmentError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise EnrollmentError(f"{label} must be a root-owned regular file, not a symlink")


def _certificate_identity(certificate_path: str) -> str:
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", certificate_path, "-noout", "-ext", "subjectAltName"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnrollmentError(f"cannot inspect Client certificate SAN: {exc}") from exc
    if result.returncode != 0:
        raise EnrollmentError("cannot parse Client certificate subjectAltName")
    lines = result.stdout.splitlines()
    if len(lines) < 2:
        raise EnrollmentError("Client certificate has no subjectAltName extension")
    identities = []
    prefixes = {
        "URI:": "URI:", "DNS:": "DNS:",
        "IP Address:": "IP:", "email:": "EMAIL:",
    }
    for item in ",".join(lines[1:]).split(","):
        token = item.strip()
        for source, target in prefixes.items():
            if token.startswith(source) and token[len(source):]:
                identities.append(target + token[len(source):])
                break
    if len(identities) != 1:
        raise EnrollmentError("Client certificate must contain exactly one supported SAN identity")
    return identities[0]

def _verify_client_certificate(certificate_path: str, ca_file: str) -> str:
    _secure_regular_file(certificate_path, "Client certificate")
    _secure_regular_file(ca_file, "deployment CA certificate")
    try:
        result = subprocess.run(
            ["openssl", "verify", "-purpose", "sslclient", "-CAfile", ca_file, certificate_path],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnrollmentError(f"could not verify Client certificate: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:512]
        raise EnrollmentError("Client certificate does not chain to the configured CA for TLS client use: " + detail)
    return _certificate_identity(certificate_path)


def inspect_client_certificate(certificate_path: str, ca_file: str) -> str:
    """Return the unique SAN identity after validating the certificate for TLS client use."""
    return _verify_client_certificate(certificate_path, ca_file)


def _load_config(config_path: str) -> dict[str, Any]:
    load_server_runtime_config(config_path)
    with open(config_path, "r", encoding="utf-8") as stream:
        value = json.load(stream)
    return value


def _write_config_atomically(config_path: str, value: dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(config_path))
    try:
        directory_info = os.lstat(directory)
    except OSError as exc:
        raise EnrollmentError(f"deployment configuration directory is unavailable: {exc}") from exc
    if (os.geteuid() != 0 or not stat.S_ISDIR(directory_info.st_mode)
            or directory_info.st_uid != 0 or directory_info.st_mode & 0o022):
        raise EnrollmentError("enrollment requires a root-owned, non-writable /etc/feclora directory")
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".deployment-server.", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, config_path)
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
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


def enroll_client_certificate(
    config_path: str,
    certificate_path: str,
    mac_address: str,
    *,
    minisign_public_key: str | None = None,
    confirmation: str,
) -> str:
    """Enroll or rotate one Client identity after CA and explicit operator checks."""
    config = _load_config(config_path)
    if not isinstance(mac_address, str) or not _MAC.fullmatch(mac_address):
        raise EnrollmentError("Client MAC address is invalid")
    mac = mac_address.lower()
    first_octet = int(mac.split(":", 1)[0], 16)
    if first_octet & 1 or mac == "00:00:00:00:00:00":
        raise EnrollmentError("Client MAC must be a unicast hardware address")
    identity = _verify_client_certificate(certificate_path, config["ca_file"])
    if (len(identity) > 256 or not re.fullmatch(r"(?:DNS|IP|URI|EMAIL):[^\x00-\x20]+", identity)):
        raise EnrollmentError("Client certificate SAN identity is not supported by the deployment configuration")
    if confirmation != f"ENROLL {identity} {mac}":
        raise EnrollmentError("enrollment confirmation does not match")
    if minisign_public_key is not None:
        _secure_regular_file(minisign_public_key, "Client minisign public key")
    identities = dict(config["client_identity_to_mac"])
    keys = dict(config["client_minisign_public_keys"])
    existing_for_mac = [item for item, enrolled_mac in identities.items() if enrolled_mac.lower() == mac]
    if identity in identities and identities[identity].lower() != mac:
        raise EnrollmentError("certificate identity is already enrolled for a different MAC")
    # Re-enrolling the same MAC rotates its certificate identity atomically.
    for old_identity in existing_for_mac:
        del identities[old_identity]
    identities[identity] = mac
    keys.pop(mac, None)
    if minisign_public_key is not None:
        keys[mac] = minisign_public_key
    config["client_identity_to_mac"] = identities
    config["client_minisign_public_keys"] = keys
    _write_config_atomically(config_path, config)
    load_server_runtime_config(config_path)
    return identity


def revoke_client_certificate(config_path: str, identity: str, *, confirmation: str) -> str:
    """Remove one Client identity and its optional image-signing trust key."""
    config = _load_config(config_path)
    if identity not in config["client_identity_to_mac"]:
        raise EnrollmentError("Client certificate identity is not enrolled")
    if confirmation != f"REVOKE {identity}":
        raise EnrollmentError("revocation confirmation does not match")
    mac = config["client_identity_to_mac"].pop(identity).lower()
    config["client_minisign_public_keys"].pop(mac, None)
    _write_config_atomically(config_path, config)
    load_server_runtime_config(config_path)
    return mac
