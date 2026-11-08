"""Temporary, interface-exclusive firewalld zone for PXE services."""
from __future__ import annotations

import re
import shutil
import subprocess
import uuid
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
        self._opened: dict[str, dict[str, Any]] = {}

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

    def _current_zone(self, interface: str) -> str | None:
        result = self._call([f"--get-zone-of-interface={interface}"], check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def open(self, interface: str, ports: Iterable[str]) -> None:
        if not _INTERFACE_RE.fullmatch(interface):
            raise PXEFirewallError("Invalid interface name for firewall scope")
        requested = list(dict.fromkeys(ports))
        if any(not _PORT_RE.fullmatch(port) or int(port.split("/", 1)[0]) > 65535 for port in requested):
            raise PXEFirewallError("Invalid PXE firewall port list")
        if interface in self._opened:
            raise PXEFirewallError(f"PXE firewall is already open for {interface}")
        self._call(["--state"])
        current = self._current_zone(interface)
        if current is None:
            current = self._call(["--get-default-zone"]).stdout.strip()
        if not current:
            raise PXEFirewallError("Could not determine the selected interface's current firewalld zone")
        explicit_interfaces = self._call([f"--zone={current}", "--list-interfaces"]).stdout.split()
        restore_zone = current if interface in explicit_interfaces else None
        zone = "feclora-pxe-" + uuid.uuid4().hex[:8]
        self._call([f"--new-zone={zone}"])
        self._opened[interface] = {
            "zone": zone,
            "restore_zone": restore_zone,
            "interface_added": False,
        }
        try:
            self._call([f"--zone={zone}", f"--add-interface={interface}"])
            self._opened[interface]["interface_added"] = True
            if self._current_zone(interface) != zone:
                raise PXEFirewallError("firewalld did not bind the selected interface exclusively to the PXE zone")
            # The named service carries firewalld's nf_conntrack_tftp helper.
            self._call([f"--zone={zone}", "--add-service=tftp"])
            for port in requested:
                self._call([f"--zone={zone}", f"--add-port={port}"])
        except PXEFirewallError as start_error:
            try:
                self.close(interface)
            except PXEFirewallError as rollback_error:
                raise PXEFirewallError(
                    f"{start_error}; firewall rollback failed: {rollback_error}"
                ) from start_error
            raise

    def close(self, interface: str) -> None:
        state = self._opened.get(interface)
        if state is None:
            return
        zone = state["zone"]
        restore_zone = state["restore_zone"]
        errors: list[str] = []

        current = self._current_zone(interface)
        if current == zone:
            result = self._call(
                [f"--zone={zone}", f"--remove-interface={interface}"],
                check=False,
            )
            if result.returncode != 0:
                errors.append("remove interface from temporary PXE zone")
            else:
                state["interface_added"] = False

        if restore_zone:
            assigned = self._call(
                [f"--zone={restore_zone}", "--list-interfaces"], check=False
            ).stdout.split()
            if interface not in assigned:
                result = self._call(
                    [f"--zone={restore_zone}", f"--add-interface={interface}"],
                    check=False,
                )
                if result.returncode != 0:
                    errors.append(f"restore interface to zone {restore_zone}")

        zones = self._call(["--get-zones"], check=False).stdout.split()
        if zone in zones:
            deleted = self._call([f"--delete-zone={zone}"], check=False)
            if deleted.returncode != 0:
                errors.append(f"delete temporary zone {zone}")

        if errors:
            raise PXEFirewallError("could not restore firewalld state: " + "; ".join(errors))
        del self._opened[interface]
