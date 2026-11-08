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


def _read_config(path: str, expected_fields: set[str]) -> dict[str, Any]:
    _secure_file(path, "deployment configuration", private=True)
    try:
        if os.path.getsize(path) > 64 * 1024:
            raise RuntimeConfigError("deployment configuration exceeds 64 KiB")
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream, object_pairs_hook=_reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"cannot read deployment configuration: {exc}") from exc
    if not isinstance(value, dict) or set(value) != expected_fields:
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
    client_identity_to_mac: Mapping[str, str]
    client_minisign_public_keys: Mapping[str, str]
    server_minisign_public_key: str
    repository: str


def load_server_runtime_config(path: str) -> ServerRuntimeConfig:
    fields = {
        "schema_version", "bind_address", "port", "local_identity", "ca_file",
        "certificate_file", "private_key_file", "client_identity_to_mac",
        "client_minisign_public_keys", "server_minisign_public_key", "repository",
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
    identities = value["client_identity_to_mac"]
    if not isinstance(identities, dict) or not identities or len(identities) > 128:
        raise RuntimeConfigError("client_identity_to_mac must contain 1-128 enrolled clients")
    normalized: dict[str, str] = {}
    seen_macs: set[str] = set()
    for identity, mac in identities.items():
        identity = _identity(identity, "client certificate identity")
        mac = _mac(mac)
        if mac in seen_macs:
            raise RuntimeConfigError("each client MAC must map to exactly one certificate identity")
        normalized[identity] = mac
        seen_macs.add(mac)
    client_keys = value["client_minisign_public_keys"]
    if not isinstance(client_keys, dict) or set(client_keys) != seen_macs:
        raise RuntimeConfigError("a minisign public key is required for every enrolled client MAC")
    checked_client_keys = {mac: _secure_file(key, "client minisign public key") for mac, key in client_keys.items()}
    return ServerRuntimeConfig(
        bind_address=address,
        port=_port(value["port"]),
        local_identity=_identity(value["local_identity"], "Server certificate identity"),
        ca_file=_secure_file(value["ca_file"], "deployment CA certificate"),
        certificate_file=_secure_file(value["certificate_file"], "Server certificate"),
        private_key_file=_secure_file(value["private_key_file"], "Server private key", private=True),
        client_identity_to_mac=normalized,
        client_minisign_public_keys=checked_client_keys,
        server_minisign_public_key=_secure_file(value["server_minisign_public_key"], "Server minisign public key"),
        repository=_repository(value["repository"]),
    )


@dataclass(frozen=True)
class ClientRuntimeConfig:
    host: str
    port: int
    local_identity: str
    server_identity: str
    mac_address: str
    ca_file: str
    certificate_file: str
    private_key_file: str
    trusted_server_public_key: str
    local_minisign_secret_key: str | None
    local_minisign_public_key: str | None
    age_identity_file: str | None
    age_recipients_file: str | None
    repository: str


def load_client_runtime_config(path: str) -> ClientRuntimeConfig:
    fields = {
        "schema_version", "host", "port", "local_identity", "server_identity",
        "mac_address", "ca_file", "certificate_file", "private_key_file",
        "trusted_server_public_key", "local_minisign_secret_key",
        "local_minisign_public_key", "age_identity_file", "age_recipients_file", "repository",
    }
    value = _read_config(path, fields)
    host = value["host"]
    if not isinstance(host, str) or not host or len(host) > 253 or any(ord(c) < 33 for c in host):
        raise RuntimeConfigError("Server host must be a valid hostname or address")
    age_identity = value["age_identity_file"]
    age_recipients = value["age_recipients_file"]
    minisign_secret = value["local_minisign_secret_key"]
    minisign_public = value["local_minisign_public_key"]
    if bool(minisign_secret) != bool(minisign_public):
        raise RuntimeConfigError("Client minisign secret and public keys must either both be configured or both be null")
    checked_minisign_secret = (
        _secure_file(minisign_secret, "Client minisign secret key", private=True)
        if minisign_secret else None
    )
    checked_minisign_public = (
        _secure_file(minisign_public, "Client minisign public key")
        if minisign_public else None
    )
    return ClientRuntimeConfig(
        host=host,
        port=_port(value["port"]),
        local_identity=_identity(value["local_identity"], "Client certificate identity"),
        server_identity=_identity(value["server_identity"], "Server certificate identity"),
        mac_address=_mac(value["mac_address"]),
        ca_file=_secure_file(value["ca_file"], "deployment CA certificate"),
        certificate_file=_secure_file(value["certificate_file"], "Client certificate"),
        private_key_file=_secure_file(value["private_key_file"], "Client private key", private=True),
        trusted_server_public_key=_secure_file(value["trusted_server_public_key"], "trusted Server minisign public key"),
        local_minisign_secret_key=checked_minisign_secret,
        local_minisign_public_key=checked_minisign_public,
        age_identity_file=_secure_file(age_identity, "age identity file", private=True) if age_identity else None,
        age_recipients_file=_secure_file(age_recipients, "age recipients file") if age_recipients else None,
        repository=_repository(value["repository"]),
    )
