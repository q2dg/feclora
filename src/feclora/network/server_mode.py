"""Interactive, explicit PXE Server-mode setup for the Fedora Live ISO."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from typing import Callable

from feclora.network.interface_discovery import (
    InterfaceAddress,
    InterfaceDiscoveryError,
    discover_interface_addresses,
)
from feclora.network.pxe_config import PXENetworkConfig, PXEConfigError
from feclora.network.pxe_service import PXEServiceError, PXEServiceManager


def list_usable_ipv4_interfaces() -> list[InterfaceAddress]:
    """Enumerate only UP interfaces with usable IPv4 addresses."""
    values: list[InterfaceAddress] = []
    for _index, name in socket.if_nameindex():
        try:
            values.extend(discover_interface_addresses(name))
        except InterfaceDiscoveryError:
            continue
    return values


def build_server_config(
    selected: InterfaceAddress,
    mode: str,
    *,
    pool_start: str | None = None,
    pool_end: str | None = None,
    gateway: str | None = None,
    dns_server: str | None = None,
    authoritative_confirmed: bool = False,
) -> PXENetworkConfig:
    config = PXENetworkConfig(
        interface=selected.interface,
        address=selected.address,
        prefix_length=selected.prefix_length,
        mode=mode,
        tftp_root="/srv/feclora/tftp",
        bios_boot_file="undionly.kpxe",
        uefi_boot_file="ipxe-snponly-x86_64.efi",
        http_root="/srv/feclora/http",
        pool_start=pool_start,
        pool_end=pool_end,
        gateway=gateway,
        dns_server=dns_server,
        authoritative_confirmed=authoritative_confirmed,
    )
    return config.validated()


def _dialog(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dialog", "--stdout", *args],
        check=False, capture_output=True, text=True,
    )


def _message(title: str, message: str) -> None:
    _dialog(["--title", title, "--msgbox", message, "12", "78"])


def _ask_input(title: str, prompt: str) -> str | None:
    result = _dialog(["--title", title, "--inputbox", prompt, "10", "76"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _elevate() -> int:
    sudo = shutil.which("sudo")
    if not sudo:
        _message("Server mode requires root", "sudo is required to manage DHCP, TFTP, Caddy and firewalld.")
        return 1
    pythonpath = os.environ.get("PYTHONPATH") or "/usr/share/feclora/python"
    term = os.environ.get("TERM") or "linux"
    result = subprocess.run(
        [sudo, "-n", "env", f"PYTHONPATH={pythonpath}", f"TERM={term}",
         sys.executable, "-m", "feclora.network.server_mode"],
        check=False,
    )
    return result.returncode


def run_server_ui(
    *,
    interface_discovery: Callable[[], list[InterfaceAddress]] = list_usable_ipv4_interfaces,
    manager_factory: Callable[[], PXEServiceManager] = PXEServiceManager,
) -> int:
    if os.geteuid() != 0:
        return _elevate()
    interfaces = interface_discovery()
    if not interfaces:
        _message("No usable interface", "No UP network interface with a usable IPv4 address was found. No service was started.")
        return 1

    choices = []
    by_tag = {}
    for index, item in enumerate(interfaces, start=1):
        tag = str(index)
        label = f"{item.interface}  {item.address}/{item.prefix_length}"
        choices.extend([tag, label])
        by_tag[tag] = item
    selected_result = _dialog([
        "--title", "PXE Server - Network interface",
        "--menu", "Choose the exact interface and IPv4 address to bind. Other interfaces will not be served.",
        "16", "82", "8", *choices,
    ])
    if selected_result.returncode != 0:
        return 0
    selected = by_tag.get(selected_result.stdout.strip())
    if selected is None:
        _message("Invalid selection", "The selected interface was not in the discovered interface list.")
        return 1

    mode_result = _dialog([
        "--title", "PXE Server - DHCP mode",
        "--menu", "ProxyDHCP is recommended on an existing LAN. Isolated DHCP is only for a dedicated network.",
        "14", "82", "4",
        "proxy", "Existing DHCP server (ProxyDHCP; no address leases)",
        "isolated", "Dedicated isolated network (Feclora assigns DHCP leases)",
    ])
    if mode_result.returncode != 0:
        return 0
    mode = mode_result.stdout.strip()
    pool_start = pool_end = gateway = dns_server = None
    confirmed = False
    if mode == "isolated":
        pool_start = _ask_input("Isolated DHCP pool", "First IPv4 address to lease:")
        if pool_start is None:
            return 0
        pool_end = _ask_input("Isolated DHCP pool", "Last IPv4 address to lease:")
        if pool_end is None:
            return 0
        gateway = _ask_input("Optional gateway", "Gateway IPv4 address (leave empty if this network has no router):")
        if gateway is None:
            return 0
        gateway = gateway or None
        dns_server = _ask_input("Optional DNS server", "DNS server IPv4 address (leave empty to omit DNS option):")
        if dns_server is None:
            return 0
        dns_server = dns_server or None
        expected = f"AUTHORITATIVE DHCP ON {selected.interface} {selected.address}/{selected.prefix_length}"
        typed = _ask_input(
            "Confirm authoritative DHCP",
            f"This will make Feclora authoritative for DHCP on the selected isolated network.\nType exactly:\n{expected}",
        )
        if typed != expected:
            _message("Confirmation did not match", "No DHCP service was started.")
            return 1
        confirmed = True

    try:
        config = build_server_config(
            selected, mode, pool_start=pool_start, pool_end=pool_end,
            gateway=gateway, dns_server=dns_server,
            authoritative_confirmed=confirmed,
        )
    except PXEConfigError as exc:
        _message("Invalid PXE configuration", str(exc))
        return 1

    summary = (
        f"Interface: {config.interface}\nAddress: {config.address}/{config.prefix_length}\n"
        f"DHCP mode: {config.mode}\nTFTP: {config.tftp_root}\n"
        f"HTTP: http://{config.address}:{config.http_port}{config.http_root}\n\n"
        "This starts DHCP/PXE/TFTP and HTTP boot services and opens only the required "
        "ports in this interface's firewalld zone. The current boot payload starts "
        "Feclora Live; authenticated deployment jobs and Client mode are not yet wired."
    )
    confirm = _dialog([
        "--title", "Confirm PXE Server startup",
        "--yesno", summary, "20", "84",
    ])
    if confirm.returncode != 0:
        return 0

    manager = manager_factory()
    try:
        manager.start(config)
        _dialog([
            "--title", "PXE Server active",
            "--menu",
            "PXE services are running. Clients can chainload iPXE and boot the Feclora Live environment. Select Stop before leaving Server mode.",
            "14", "82", "2",
            "stop", "Stop PXE services and close the firewall ports",
        ])
    except (PXEServiceError, Exception) as exc:
        _message("PXE Server failed", str(exc))
        return 1
    finally:
        try:
            manager.stop()
        except PXEServiceError as exc:
            _message("PXE shutdown warning", str(exc))
    _message("PXE Server stopped", "dnsmasq, Caddy and Feclora's runtime firewall rules have been stopped.")
    return 0


def main() -> int:
    if shutil.which("dialog") is None:
        print("feclora: install the 'dialog' package to use this interface", file=sys.stderr)
        return 1
    return run_server_ui()


if __name__ == "__main__":
    raise SystemExit(main())
