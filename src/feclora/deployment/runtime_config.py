"""Root-owned runtime configuration for authenticated deployment endpoints."""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from typing import Any, Mapping


class RuntimeConfigError(RuntimeError):
    """Deployment runtime configuration is missing, unsafe or malformed."""


_MAC = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_IDENTITY = re.compile(r"^(?:DNS|IP|URI|EMAIL):.+$|^sha256:[0-9a-fA-F]{64}$")


def _secure_file(path: Any, label: str, *, private: bool = False) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise RuntimeConfigError(f"{label} path must be absolute")
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeConfigError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise RuntimeConfigError(f"{label} must be a root-owned regular file, not a symlink")
    if private and info.st_mode & 0o077:
        raise RuntimeConfigError(f"{label} must not be accessible by group or other users")
    return path


def _repository(path: Any) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise RuntimeConfigError("image repository path must be absolute")
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeConfigError(f"image repository is unavailable: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeConfigError("image repository must be a root-owned real directory and not group/other-writable")
    return path


def _read_config(path: str, expected_fields: set[str], optional_fields: set[str] | None = None) -> dict[str, Any]:
    _secure_file(path, "deployment configuration", private=True)
    try:
        if os.path.getsize(path) > 64 * 1024:
            raise RuntimeConfigError("deployment configuration exceeds 64 KiB")
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream, object_pairs_hook=_reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"cannot read deployment configuration: {exc}") from exc
    optional = optional_fields or set()
    if (not isinstance(value, dict) or not expected_fields.issubset(value)
            or set(value) - expected_fields - optional):
        raise RuntimeConfigError("deployment configuration has missing or unknown fields")
    if value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool):
        raise RuntimeConfigError("unsupported deployment configuration schema")
    return value


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeConfigError(f"duplicate configuration field: {key}")
        result[key] = value
    return result


def _port(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= 65535:
        raise RuntimeConfigError("deployment control port must be between 1024 and 65535")
    return value


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value) or len(value) > 256:
        raise RuntimeConfigError(f"{label} must be a SAN identity or SHA-256 certificate pin")
    return value.lower() if value.startswith("sha256:") else value


def _mac(value: Any) -> str:
    if not isinstance(value, str) or not _MAC.fullmatch(value):
        raise RuntimeConfigError("client MAC address is invalid")
    normalized = value.lower()
    first = int(normalized.split(":", 1)[0], 16)
    if first & 1 or normalized == "00:00:00:00:00:00":
        raise RuntimeConfigError("client MAC must be a unicast hardware address")
    return normalized


@dataclass(frozen=True)
class ServerRuntimeConfig:
    bind_address: str
    port: int
    local_identity: str
    ca_file: str
    certificate_file: str
    private_key_file: str
    repository: str
    client_identity_to_mac: Mapping[str, str]


def load_server_runtime_config(path: str) -> ServerRuntimeConfig:
    fields = {
        "schema_version", "bind_address", "port", "local_identity", "ca_file",
        "certificate_file", "private_key_file", "client_identity_to_mac",
        "repository",
    }
    value = _read_config(path, fields)
    address = value["bind_address"]
    if not isinstance(address, str) or not address:
        raise RuntimeConfigError("bind_address must be a concrete interface address")
    try:
        import ipaddress
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise RuntimeConfigError("bind_address must be an IPv4 or IPv6 address") from exc
    if parsed.version != 4 or parsed.is_unspecified or parsed.is_multicast:
        raise RuntimeConfigError("bind_address must be a concrete unicast interface address")
    enrollment = value["client_identity_to_mac"]
    if not isinstance(enrollment, dict):
        raise RuntimeConfigError("client_identity_to_mac must be an object")
    normalized_enrollment: dict[str, str] = {}
    for identity, mac in enrollment.items():
        checked_identity = _identity(identity, "Client certificate identity")
        checked_mac = _mac(mac)
        if checked_identity in normalized_enrollment or checked_mac in normalized_enrollment.values():
            raise RuntimeConfigError("client enrollment identities and MAC addresses must be unique")
        normalized_enrollment[checked_identity] = checked_mac
    return ServerRuntimeConfig(
        bind_address=address,
        port=_port(value["port"]),
        local_identity=_identity(value["local_identity"], "Server certificate identity"),
        ca_file=_secure_file(value["ca_file"], "deployment CA certificate"),
        certificate_file=_secure_file(value["certificate_file"], "Server certificate"),
        private_key_file=_secure_file(value["private_key_file"], "Server private key", private=True),
        repository=_repository(value["repository"]),
        client_identity_to_mac=normalized_enrollment,
    )


@dataclass(frozen=True)
class ClientRuntimeConfig:
    host: str
    port: int
    server_identity: str
    mac_address: str
    ca_file: str
    age_identity_file: str | None
    age_recipients_file: str | None
    repository: str


def load_client_runtime_config(path: str) -> ClientRuntimeConfig:
    fields = {
        "schema_version", "host", "port", "server_identity",
        "mac_address", "ca_file",
        "age_identity_file", "age_recipients_file", "repository",
    }
    value = _read_config(path, fields, {"local_identity", "certificate_file", "private_key_file"})
    host = value["host"]
    if not isinstance(host, str) or not host or len(host) > 253 or any(ord(c) < 33 for c in host):
        raise RuntimeConfigError("Server host must be a valid hostname or address")
    age_identity = value["age_identity_file"]
    age_recipients = value["age_recipients_file"]
    return ClientRuntimeConfig(
        host=host,
        port=_port(value["port"]),
        server_identity=_identity(value["server_identity"], "Server certificate identity"),
        mac_address=_mac(value["mac_address"]),
        ca_file=_secure_file(value["ca_file"], "deployment CA certificate"),
        age_identity_file=_secure_file(age_identity, "age identity file", private=True) if age_identity is not None else None,
        age_recipients_file=_secure_file(age_recipients, "age recipients file") if age_recipients is not None else None,
        repository=_repository(value["repository"]),
    )
