"""Apply NetworkManager IPv4 profiles with an automatic rollback checkpoint."""
from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess
from typing import Callable


class NetworkApplyError(RuntimeError):
    """A network profile could not be applied and verified."""


_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_NM_PATH = "/org/freedesktop/NetworkManager"
_NM_IFACE = "org.freedesktop.NetworkManager"


def _run(
    argv: list[str], *, runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: int = 15, input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            argv, stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
            input=input_text, capture_output=True, text=True, check=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkApplyError(f"network command failed: {exc}") from exc


def validate_ipv4_profile(
    *, uuid: str, interface: str, method: str, address: str | None = None,
    prefix_length: int | None = None, gateway: str | None = None,
    dns: list[str] | None = None,
) -> list[str]:
    if not isinstance(uuid, str) or not _UUID_RE.fullmatch(uuid):
        raise NetworkApplyError("A valid NetworkManager profile UUID is required")
    if not isinstance(interface, str) or not _IFACE_RE.fullmatch(interface):
        raise NetworkApplyError("Invalid network interface name")
    if method not in {"auto", "manual"}:
        raise NetworkApplyError("IPv4 method must be DHCP (auto) or static (manual)")
    if dns is None:
        dns = []
    if not isinstance(dns, list) or len(dns) > 4:
        raise NetworkApplyError("DNS must contain at most four IPv4 addresses")
    parsed_dns = []
    for server in dns:
        try:
            ip = ipaddress.ip_address(server)
        except (ValueError, TypeError) as exc:
            raise NetworkApplyError("DNS entries must be IPv4 addresses") from exc
        if ip.version != 4 or ip.is_unspecified or ip.is_multicast:
            raise NetworkApplyError("DNS entries must be usable IPv4 addresses")
        parsed_dns.append(str(ip))
    args = ["connection", "modify", "uuid", uuid, "ipv4.method", method]
    if method == "auto":
        if any(value is not None for value in (address, prefix_length, gateway)) or parsed_dns:
            raise NetworkApplyError("DHCP configuration must not include static address, gateway or DNS values")
        args += ["ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", "", "ipv4.ignore-auto-dns", "no"]
    else:
        if not isinstance(prefix_length, int) or isinstance(prefix_length, bool) or not 1 <= prefix_length <= 30:
            raise NetworkApplyError("Static IPv4 prefix must be between 1 and 30")
        try:
            ip = ipaddress.ip_address(address)
        except (ValueError, TypeError) as exc:
            raise NetworkApplyError("Static address must be IPv4") from exc
        if ip.version != 4 or ip.is_unspecified or ip.is_loopback or ip.is_multicast:
            raise NetworkApplyError("Static address must be a usable unicast IPv4 address")
        network = ipaddress.ip_network(f"{ip}/{prefix_length}", strict=False)
        if ip in (network.network_address, network.broadcast_address):
            raise NetworkApplyError("Static address cannot be the subnet or broadcast address")
        if gateway:
            try:
                gw = ipaddress.ip_address(gateway)
            except ValueError as exc:
                raise NetworkApplyError("Gateway must be an IPv4 address") from exc
            if gw.version != 4 or gw not in network or gw == ip:
                raise NetworkApplyError("Gateway must be a different address inside the static subnet")
        args += ["ipv4.addresses", f"{ip}/{prefix_length}", "ipv4.gateway", gateway or "",
                 "ipv4.dns", ",".join(parsed_dns), "ipv4.ignore-auto-dns", "yes"]
    return args


def apply_ipv4_profile(
    *, uuid: str, interface: str, method: str, address: str | None = None,
    prefix_length: int | None = None, gateway: str | None = None,
    dns: list[str] | None = None, rollback_timeout: int = 120,
    nmcli: str | None = None, busctl: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    if isinstance(rollback_timeout, bool) or not isinstance(rollback_timeout, int) or not 60 <= rollback_timeout <= 300:
        raise NetworkApplyError("Rollback timeout must be between 60 and 300 seconds")
    nmcli = nmcli or shutil.which("nmcli")
    busctl = busctl or shutil.which("busctl")
    if not nmcli or not busctl:
        raise NetworkApplyError("NetworkManager nmcli and busctl are required")
    modify = validate_ipv4_profile(
        uuid=uuid, interface=interface, method=method, address=address,
        prefix_length=prefix_length, gateway=gateway, dns=dns,
    )
    # Limit the checkpoint to the selected interface; an unresponsive Cockpit
    # client cannot prevent NetworkManager's timed automatic rollback.
    device = _run(
        [nmcli, "-g", "GENERAL.DBUS-PATH", "device", "show", interface],
        runner=runner,
    ).stdout.strip()
    if not device.startswith("/org/freedesktop/NetworkManager/Devices/"):
        raise NetworkApplyError("NetworkManager did not return a valid device object")
    checkpoint = _run(
        [busctl, "call", "org.freedesktop.NetworkManager", _NM_PATH,
         _NM_IFACE, "CheckpointCreate", "aouu", "1", device,
         str(rollback_timeout), "0"],
        runner=runner,
    ).stdout.strip().split()
    checkpoint_path = checkpoint[-1].strip('"') if len(checkpoint) >= 2 else ""
    if not checkpoint_path.startswith("/org/freedesktop/NetworkManager/Checkpoint"):
        raise NetworkApplyError("NetworkManager did not create a valid rollback checkpoint")
    try:
        _run([nmcli, *modify], runner=runner)
        _run([nmcli, "--wait", "45", "connection", "up", "uuid", uuid, "ifname", interface],
             runner=runner, timeout=55)
        active = _run(
            [nmcli, "-g", "GENERAL.CON-UUID", "device", "show", interface],
            runner=runner,
        ).stdout.strip()
        if active.lower() != uuid.lower():
            raise NetworkApplyError("The selected profile is not active on the requested interface")
        addresses = _run(
            [nmcli, "-g", "IP4.ADDRESS", "device", "show", interface],
            runner=runner,
        ).stdout.strip()
        if method == "manual":
            expected = f"{address}/{prefix_length}"
            if expected not in addresses.splitlines():
                raise NetworkApplyError("The requested static IPv4 address was not observed after activation")
        elif not addresses:
            raise NetworkApplyError("DHCP did not assign an IPv4 address")
        _run(
            [busctl, "call", "org.freedesktop.NetworkManager", _NM_PATH,
             _NM_IFACE, "CheckpointDestroy", "o", checkpoint_path],
            runner=runner,
        )
        return {"uuid": uuid, "interface": interface, "method": method,
                "address": addresses.splitlines()[0] if addresses else ""}
    except Exception:
        # Explicit rollback is best-effort; the checkpoint timeout remains the
        # final safety net if this process or the management connection dies.
        try:
            _run(
                [busctl, "call", "org.freedesktop.NetworkManager", _NM_PATH,
                 _NM_IFACE, "CheckpointRollback", "o", checkpoint_path],
                runner=runner,
            )
        except NetworkApplyError:
            pass
        raise
