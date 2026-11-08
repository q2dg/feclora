"""Interface-scoped, runtime-only firewalld rules for PXE services."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Callable, Iterable


class PXEFirewallError(RuntimeError):
    """PXE firewall rules could not be applied or removed safely."""


_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_PORT_RE = re.compile(r"^(?:[1-9][0-9]{0,4})/(?:tcp|udp)$")


class PXEFirewall:
    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.executable = executable or shutil.which("firewall-cmd")
        self.runner = runner
        self._opened: dict[str, tuple[str, list[str], list[str]]] = {}

    def _call(self, args: list[str], *, check: bool = True) -> Any:
        if not self.executable:
            raise PXEFirewallError("firewall-cmd is required; refusing to start PXE without scoped firewall rules")
        try:
            result = self.runner(
                [self.executable, *args], check=False,
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PXEFirewallError(f"firewall-cmd failed: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise PXEFirewallError(detail or "firewall-cmd command failed")
        return result

    def open(self, interface: str, ports: Iterable[str]) -> None:
        if not _INTERFACE_RE.fullmatch(interface):
            raise PXEFirewallError("Invalid interface name for firewall scope")
        requested = list(dict.fromkeys(ports))
        if any(not _PORT_RE.fullmatch(port) or int(port.split("/", 1)[0]) > 65535 for port in requested):
            raise PXEFirewallError("Invalid PXE firewall port list")
        if interface in self._opened:
            raise PXEFirewallError(f"PXE firewall is already open for {interface}")
        self._call(["--state"])
        zone_result = self._call([f"--get-zone-of-interface={interface}"], check=False)
        if zone_result.returncode == 0 and zone_result.stdout.strip():
            zone = zone_result.stdout.strip()
        else:
            zone = self._call(["--get-default-zone"]).stdout.strip()
        if not zone or any(ch.isspace() for ch in zone):
            raise PXEFirewallError("Could not determine the selected interface firewalld zone")
        added_ports: list[str] = []
        added_services: list[str] = []
        try:
            # firewalld's named TFTP service also enables nf_conntrack_tftp,
            # required for the server's dynamically negotiated data channel.
            tftp = self._call([f"--zone={zone}", "--query-service=tftp"], check=False)
            if tftp.returncode == 1:
                self._call([f"--zone={zone}", "--add-service=tftp"])
                added_services.append("tftp")
            elif tftp.returncode != 0:
                raise PXEFirewallError("cannot query existing TFTP firewall service")
            for port in requested:
                query = self._call([f"--zone={zone}", f"--query-port={port}"], check=False)
                if query.returncode == 0:
                    continue
                if query.returncode != 1:
                    raise PXEFirewallError(f"cannot query existing firewall rule {port}")
                self._call([f"--zone={zone}", f"--add-port={port}"])
                added_ports.append(port)
        except PXEFirewallError:
            for port in reversed(added_ports):
                self._call([f"--zone={zone}", f"--remove-port={port}"], check=False)
            for service in reversed(added_services):
                self._call([f"--zone={zone}", f"--remove-service={service}"], check=False)
            raise
        self._opened[interface] = (zone, added_ports, added_services)

    def close(self, interface: str) -> None:
        state = self._opened.get(interface)
        if state is None:
            return
        zone, ports, services = state
        remaining_ports = []
        remaining_services = []
        for port in reversed(ports):
            result = self._call([f"--zone={zone}", f"--remove-port={port}"], check=False)
            if result.returncode != 0:
                remaining_ports.append(port)
        for service in reversed(services):
            result = self._call([f"--zone={zone}", f"--remove-service={service}"], check=False)
            if result.returncode != 0:
                remaining_services.append(service)
        if remaining_ports or remaining_services:
            self._opened[interface] = (
                zone, list(reversed(remaining_ports)), list(reversed(remaining_services))
            )
            failed = remaining_ports + remaining_services
            raise PXEFirewallError("could not remove runtime firewall entries: " + ", ".join(failed))
        del self._opened[interface]
