"""Local host-side multicast readiness checks; switch IGMP state remains operator-verified."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


class MulticastPreflightError(RuntimeError):
    """The selected endpoint cannot safely participate in the multicast job."""


@dataclass(frozen=True)
class MulticastPreflight:
    interface: str
    ipv4_address: str
    route_interface: str
    warnings: tuple[str, ...]


def inspect_multicast_interface(
    interface: str,
    group: str,
    *,
    role: str,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    ip: str = "/usr/sbin/ip",
) -> MulticastPreflight:
    """Check interface state, IPv4 address, kernel multicast route and required binaries."""
    if not isinstance(interface, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", interface):
        raise MulticastPreflightError("multicast interface name is invalid")
    if role not in {"sender", "receiver"}:
        raise MulticastPreflightError("multicast preflight role must be sender or receiver")
    try:
        import ipaddress
        address = ipaddress.ip_address(group)
    except ValueError as exc:
        raise MulticastPreflightError("multicast group is not a valid IPv4 address") from exc
    if address.version != 4 or not address.is_multicast:
        raise MulticastPreflightError("multicast group must be an IPv4 multicast address")
    execute = runner or subprocess.run

    def query(argv: list[str], label: str) -> str:
        try:
            result = execute(argv, stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MulticastPreflightError(f"{label} could not run: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:256]
            raise MulticastPreflightError(f"{label} failed" + (f": {detail}" if detail else ""))
        return result.stdout

    link = query([ip, "-o", "link", "show", "dev", interface], "interface inspection")
    flags = re.search(r"<([^>]+)>", link)
    flag_set = set(flags.group(1).split(",")) if flags else set()
    if "UP" not in flag_set or "MULTICAST" not in flag_set:
        raise MulticastPreflightError("selected interface must be UP and support multicast")
    address_output = query([ip, "-o", "-4", "addr", "show", "dev", interface], "IPv4 interface inspection")
    ipv4 = re.search(r"\\binet\\s+([0-9.]+)/[0-9]+", address_output)
    if not ipv4:
        raise MulticastPreflightError("selected multicast interface has no IPv4 address")
    route_output = query([ip, "-4", "route", "get", str(address)], "multicast route inspection")
    route = re.search(r"\\bdev\\s+(\\S+)", route_output)
    if not route:
        raise MulticastPreflightError("kernel did not select a route for the multicast group")
    if route.group(1) != interface:
        raise MulticastPreflightError(
            f"kernel multicast route uses {route.group(1)}, not selected interface {interface}"
        )
    required = ["udp-sender"] if role == "sender" else ["udp-receiver"]
    for binary in required:
        if not which(binary):
            raise MulticastPreflightError(f"{binary} is required for the selected multicast role")
    return MulticastPreflight(
        interface=interface,
        ipv4_address=ipv4.group(1),
        route_interface=route.group(1),
        warnings=(
            "The host cannot verify switch IGMP snooping or querier configuration. Confirm both on the same VLAN before arming the job.",
            "This Feclora profile uses TTL=1; routed multicast and Wi-Fi client isolation are not supported.",
        ),
    )
