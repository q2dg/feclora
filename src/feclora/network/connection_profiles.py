"""Read-only NetworkManager connection profile inventory for Cockpit."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Callable


class NetworkProfileError(RuntimeError):
    """NetworkManager profiles could not be inspected safely."""


_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def parse_connection_profiles(payload: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise NetworkProfileError("nmcli returned invalid JSON") from exc
    if not isinstance(rows, list):
        raise NetworkProfileError("nmcli profile inventory must be an array")
    profiles = []
    for row in rows:
        if not isinstance(row, dict):
            raise NetworkProfileError("nmcli profile entry is malformed")
        uuid = row.get("UUID")
        name = row.get("NAME")
        kind = row.get("TYPE")
        if not isinstance(uuid, str) or not _UUID_RE.fullmatch(uuid):
            continue
        if not isinstance(name, str) or not name or len(name) > 256:
            continue
        if kind not in {"ethernet", "wifi", "vlan", "bond", "bridge"}:
            continue
        method = row.get("ipv4.method", row.get("IP4.METHOD", "auto"))
        if method not in {"auto", "manual", "disabled", "link-local", "shared"}:
            method = "unknown"
        addresses = row.get("ipv4.addresses", row.get("IP4.ADDRESS", []))
        if isinstance(addresses, str):
            addresses = [addresses] if addresses else []
        if not isinstance(addresses, list) or any(not isinstance(v, str) for v in addresses):
            addresses = []
        profiles.append({
            "uuid": uuid, "name": name, "type": kind,
            "device": row.get("DEVICE") if isinstance(row.get("DEVICE"), str) else None,
            "active": str(row.get("ACTIVE", "no")).lower() in {"yes", "true", "1"},
            "autoconnect": str(row.get("connection.autoconnect", "yes")).lower() in {"yes", "true", "1"},
            "ipv4_method": method,
            "ipv4_addresses": addresses[:8],
            "ipv4_gateway": row.get("ipv4.gateway", row.get("IP4.GATEWAY")) if isinstance(row.get("ipv4.gateway", row.get("IP4.GATEWAY")), str) else None,
            "ipv4_dns": dns[:4],
        })
    return profiles


def list_connection_profiles(
    *, executable: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    nmcli = executable or shutil.which("nmcli")
    if not nmcli:
        raise NetworkProfileError("NetworkManager (nmcli) is required")
    fields = "NAME,UUID,TYPE,DEVICE,ACTIVE,connection.autoconnect,ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns"
    # JSON output avoids delimiter ambiguity in connection names and addresses.
    try:
        result = runner(
            [nmcli, "--mode", "json", "--fields", fields, "connection", "show"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkProfileError(f"cannot inspect NetworkManager profiles: {exc}") from exc
    return parse_connection_profiles(result.stdout)
