"""Read-only Linux interface/address discovery for PXE preflight."""
from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


class InterfaceDiscoveryError(RuntimeError):
    """The selected deployment interface cannot be safely identified."""


_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


@dataclass(frozen=True)
class InterfaceAddress:
    interface: str
    address: str
    prefix_length: int
    scope: str
    flags: tuple[str, ...] = ()

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_network(
            f"{self.address}/{self.prefix_length}", strict=False
        )


def parse_interface_addresses(payload: str, interface: str) -> list[InterfaceAddress]:
    if not _INTERFACE_RE.fullmatch(interface):
        raise InterfaceDiscoveryError("Invalid Linux interface name")
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InterfaceDiscoveryError(f"ip returned invalid JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise InterfaceDiscoveryError("ip JSON must be an array")
    found = []
    for row in rows:
        if not isinstance(row, dict) or row.get("ifname") != interface:
            continue
        flags = tuple(str(flag) for flag in row.get("flags", []))
        if "UP" not in flags or "LOOPBACK" in flags:
            continue
        addr_info = row.get("addr_info", [])
        if not isinstance(addr_info, list):
            raise InterfaceDiscoveryError("ip address list is malformed")
        for address in addr_info:
            if not isinstance(address, dict) or address.get("family") != "inet":
                continue
            local = address.get("local")
            prefix = address.get("prefixlen")
            try:
                parsed = ipaddress.ip_address(local)
            except (ValueError, TypeError):
                continue
            if parsed.version != 4 or parsed.is_unspecified or parsed.is_loopback or parsed.is_multicast:
                continue
            if isinstance(prefix, bool) or not isinstance(prefix, int) or not 1 <= prefix <= 30:
                continue
            found.append(InterfaceAddress(
                interface=interface,
                address=str(parsed),
                prefix_length=prefix,
                scope=str(address.get("scope") or ""),
                flags=flags,
            ))
    return found


def discover_interface_addresses(
    interface: str,
    *,
    executable: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[InterfaceAddress]:
    if not _INTERFACE_RE.fullmatch(interface):
        raise InterfaceDiscoveryError("Invalid Linux interface name")
    ip = executable or shutil.which("ip")
    if not ip:
        raise InterfaceDiscoveryError("iproute is required for interface discovery")
    try:
        completed = runner(
            [ip, "-j", "-4", "address", "show", "dev", interface],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise InterfaceDiscoveryError("Interface discovery timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise InterfaceDiscoveryError(detail or f"cannot inspect interface {interface}") from exc
    addresses = parse_interface_addresses(completed.stdout, interface)
    if not addresses:
        raise InterfaceDiscoveryError(
            f"Interface {interface} has no usable IPv4 address and is not UP"
        )
    return addresses


def validate_selected_address(
    interface: str,
    address: str,
    prefix_length: int,
    discovered: list[InterfaceAddress],
) -> InterfaceAddress:
    matches = [
        item for item in discovered
        if item.interface == interface
        and item.address == address
        and item.prefix_length == prefix_length
    ]
    if len(matches) != 1:
        raise InterfaceDiscoveryError(
            "Selected IPv4 address/prefix is not currently assigned to the selected interface"
        )
    return matches[0]



def detect_existing_dhcp_server(
    interface: str,
    *,
    nmcli: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str | None:
    """Return a DHCP server identifier from the current NetworkManager lease, if any.

    Absence of a lease identifier is not evidence that the network is isolated.
    """
    if not _INTERFACE_RE.fullmatch(interface):
        raise InterfaceDiscoveryError("Invalid Linux interface name")
    executable = nmcli or shutil.which("nmcli")
    if executable is None:
        return None
    try:
        completed = runner(
            [executable, "-g", "DHCP4.OPTION", "device", "show", interface],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().lower() in {
            "dhcp_server_identifier", "dhcp-server-identifier",
        }:
            candidate = value.strip()
            try:
                parsed = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if parsed.version == 4 and not parsed.is_unspecified and not parsed.is_multicast:
                return str(parsed)
    return None
