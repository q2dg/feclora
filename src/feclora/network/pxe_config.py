"""Safe configuration generation for feclora's embedded PXE services.

This module is deliberately side-effect free: importing it never opens sockets,
writes files, or starts system services.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import re


class PXEConfigError(ValueError):
    """Raised when a PXE network profile is incomplete or unsafe."""


_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


@dataclass(frozen=True)
class PXENetworkConfig:
    interface: str
    address: str
    prefix_length: int
    mode: str
    tftp_root: str
    bios_boot_file: str
    uefi_boot_file: str
    http_root: str
    http_port: int = 8080
    pool_start: str | None = None
    pool_end: str | None = None
    lease_time: str = "1h"
    gateway: str | None = None
    dns_server: str | None = None
    authoritative_confirmed: bool = False

    def validated(self) -> "PXENetworkConfig":
        if not isinstance(self.interface, str) or not _INTERFACE_RE.fullmatch(self.interface):
            raise PXEConfigError("Invalid Linux interface name")
        if not isinstance(self.address, str):
            raise PXEConfigError("A selected interface IPv4 address is required")
        try:
            address = ipaddress.ip_address(self.address)
        except ValueError as exc:
            raise PXEConfigError("Deployment address must be IPv4") from exc
        if address.version != 4 or address.is_unspecified or address.is_loopback or address.is_multicast:
            raise PXEConfigError("Deployment address must be a usable unicast IPv4 address")
        if isinstance(self.prefix_length, bool) or not isinstance(self.prefix_length, int) or not 1 <= self.prefix_length <= 30:
            raise PXEConfigError("IPv4 prefix length must be between 1 and 30")
        network = ipaddress.ip_network(f"{address}/{self.prefix_length}", strict=False)
        if address not in network or address in (network.network_address, network.broadcast_address):
            raise PXEConfigError("Deployment address cannot be the subnet or broadcast address")
        if self.mode not in {"proxy", "isolated"}:
            raise PXEConfigError("DHCP mode must be 'proxy' or 'isolated'")
        for label, path in (("TFTP root", self.tftp_root), ("HTTP root", self.http_root)):
            if not isinstance(path, str) or not path.startswith("/") or "\n" in path or "\r" in path:
                raise PXEConfigError(f"{label} must be an absolute filesystem path")
        for label, filename in (("BIOS boot file", self.bios_boot_file), ("UEFI boot file", self.uefi_boot_file)):
            if not isinstance(filename, str) or not _FILENAME_RE.fullmatch(filename):
                raise PXEConfigError(f"{label} must be a simple filename")
        if isinstance(self.http_port, bool) or not isinstance(self.http_port, int) or not 1 <= self.http_port <= 65535:
            raise PXEConfigError("HTTP port must be between 1 and 65535")
        for label, value in (("gateway", self.gateway), ("DNS server", self.dns_server)):
            if value is not None:
                try:
                    parsed = ipaddress.ip_address(value)
                except ValueError as exc:
                    raise PXEConfigError(f"{label} must be an IPv4 address") from exc
                if parsed.version != 4:
                    raise PXEConfigError(f"{label} must be an IPv4 address")
        if self.mode == "proxy":
            if any(value is not None for value in (self.pool_start, self.pool_end, self.gateway, self.dns_server)):
                raise PXEConfigError("ProxyDHCP must not define an address pool, gateway or DNS options")
            if self.authoritative_confirmed:
                raise PXEConfigError("ProxyDHCP cannot be authoritative DHCP")
        else:
            if self.authoritative_confirmed is not True:
                raise PXEConfigError("Isolated DHCP requires explicit authoritative-DHCP confirmation")
            if not self.pool_start or not self.pool_end:
                raise PXEConfigError("Isolated DHCP requires an explicit address pool")
            try:
                start = ipaddress.ip_address(self.pool_start)
                end = ipaddress.ip_address(self.pool_end)
            except ValueError as exc:
                raise PXEConfigError("DHCP pool endpoints must be IPv4 addresses") from exc
            if start.version != 4 or end.version != 4 or int(start) > int(end):
                raise PXEConfigError("Invalid DHCP address pool")
            if start not in network or end not in network or address in (start, end) or start <= address <= end:
                raise PXEConfigError("DHCP pool must be inside the selected subnet and exclude the server address")
            if start in (network.network_address, network.broadcast_address) or end in (network.network_address, network.broadcast_address):
                raise PXEConfigError("DHCP pool cannot include network or broadcast addresses")
            if self.gateway and ipaddress.ip_address(self.gateway) not in network:
                raise PXEConfigError("Gateway must be inside the selected subnet")
            if self.dns_server and ipaddress.ip_address(self.dns_server).version != 4:
                raise PXEConfigError("DNS server must be IPv4")
        return self

    @property
    def network(self) -> ipaddress.IPv4Network:
        self.validated()
        return ipaddress.ip_network(f"{self.address}/{self.prefix_length}", strict=False)


def render_dnsmasq(config: PXENetworkConfig) -> str:
    """Render a single-interface dnsmasq profile without wildcard listeners."""
    config.validated()
    network = config.network
    lines = [
        "# Generated by feclora; do not edit while Server mode is active.",
        "port=0",
        "interface=" + config.interface,
        "except-interface=lo",
        "bind-interfaces",
        "listen-address=" + config.address,
        "dhcp-no-override",
        "log-dhcp",
        "enable-tftp",
        "tftp-root=" + config.tftp_root,
        "tftp-secure",
        "dhcp-match=set:ipxe,option:vendor-class,iPXE",
        "dhcp-match=set:efi64,option:client-arch,7",
        "dhcp-match=set:efi64,option:client-arch,9",
        "dhcp-match=set:bios,option:client-arch,0",
        "dhcp-boot=tag:ipxe,http://" + config.address + ":" + str(config.http_port) + "/boot.ipxe",
        "dhcp-boot=net:bios," + config.bios_boot_file,
        "dhcp-boot=net:efi64," + config.uefi_boot_file,
        "dhcp-option=option:router," + (config.gateway or config.address) if config.mode == "isolated" else "# ProxyDHCP does not assign router options",
    ]
    if config.mode == "proxy":
        lines.extend([
            "dhcp-range=" + str(network) + ",proxy",
            "dhcp-no-override",
        ])
    else:
        lines.extend([
            "dhcp-authoritative",
            f"dhcp-range={config.pool_start},{config.pool_end},{network.netmask},{config.lease_time}",
        ])
        if config.dns_server:
            lines.append("dhcp-option=option:dns-server," + config.dns_server)
    return "\n".join(lines) + "\n"


def render_caddy(config: PXENetworkConfig) -> str:
    """Render plain HTTP bound only to the selected deployment IPv4 address."""
    config.validated()
    root = json.dumps(config.http_root)
    return (
        f"http://{config.address}:{config.http_port} {{\n"
        f"    root * {root}\n"
        "    file_server\n"
        "    log {\n"
        "        output stdout\n"
        "    }\n"
        "}\n"
    )
