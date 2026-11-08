"""Temporary, interface-exclusive firewalld zone for Feclora network services."""
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
        self.on_change: Callable[[str], None] | None = None

    def _notify(self, interface: str) -> None:
        if self.on_change is not None:
            self.on_change(interface)

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

    def open(self, interface: str, ports: Iterable[str], *, include_tftp: bool = True) -> None:
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
            "ports": list(requested),
        }
        try:
            self._call([f"--zone={zone}", f"--add-interface={interface}"])
            self._opened[interface]["interface_added"] = True
            if self._current_zone(interface) != zone:
                raise PXEFirewallError("firewalld did not bind the selected interface exclusively to the PXE zone")
            # The named service carries firewalld's nf_conntrack_tftp helper.
            if include_tftp:
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

    def export_state(self, interface: str) -> dict[str, Any]:
        """Return the exact temporary zone state needed to stop it in a later process."""
        state = self._opened.get(interface)
        if state is None:
            raise PXEFirewallError("No active Feclora temporary firewall zone for interface")
        if self._current_zone(interface) != state["zone"]:
            raise PXEFirewallError("Selected interface is no longer attached to the Feclora PXE zone")
        result = {
            "zone": state["zone"],
            "restore_zone": state["restore_zone"],
            "ports": list(state["ports"]),
        }
        if "protocols" in state:
            result["protocols"] = list(state["protocols"])
        return result

    def adopt(self, interface: str, state: dict[str, Any]) -> None:
        """Reattach this manager to a previously persisted Feclora runtime zone."""
        if not _INTERFACE_RE.fullmatch(interface):
            raise PXEFirewallError("Invalid interface name for firewall recovery")
        if not isinstance(state, dict) or set(state) not in (
            {"zone", "restore_zone", "ports"},
            {"zone", "restore_zone", "ports", "protocols"},
        ):
            raise PXEFirewallError("Persisted PXE firewall state is malformed")
        zone, restore_zone, ports = state["zone"], state["restore_zone"], state["ports"]
        if not isinstance(zone, str) or not re.fullmatch(r"feclora-pxe-[0-9a-f]{8}", zone):
            raise PXEFirewallError("Persisted PXE firewall zone name is invalid")
        if restore_zone is not None and (
            not isinstance(restore_zone, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", restore_zone)
        ):
            raise PXEFirewallError("Persisted original firewall zone is invalid")
        if not isinstance(ports, list) or any(
            not isinstance(port, str) or not _PORT_RE.fullmatch(port)
            or int(port.split("/", 1)[0]) > 65535 for port in ports
        ):
            raise PXEFirewallError("Persisted PXE firewall port list is invalid")
        protocols = state.get("protocols", [])
        if not isinstance(protocols, list) or any(
            not isinstance(protocol, str) or not re.fullmatch(r"[a-z0-9-]{1,32}", protocol)
            for protocol in protocols
        ):
            raise PXEFirewallError("Persisted PXE firewall protocol list is invalid")
        if self._current_zone(interface) != zone:
            raise PXEFirewallError("Refusing to adopt a PXE firewall zone not currently assigned to the selected interface")
        if interface in self._opened:
            raise PXEFirewallError("PXE firewall is already attached to this interface")
        self._opened[interface] = {
            "zone": zone, "restore_zone": restore_zone,
            "interface_added": True, "ports": list(ports),
            **({"protocols": list(protocols)} if "protocols" in state else {}),
        }

    def is_open(self, interface: str) -> bool:
        """Return whether this manager currently owns a temporary zone for interface."""
        return interface in self._opened

    def add_ports(self, interface: str, ports: Iterable[str]) -> tuple[str, ...]:
        """Add temporary ports to an active zone without replacing existing PXE rules."""
        state = self._opened.get(interface)
        if state is None or self._current_zone(interface) != state["zone"]:
            raise PXEFirewallError("No active Feclora temporary firewall zone for interface")
        requested = list(dict.fromkeys(ports))
        if any(not _PORT_RE.fullmatch(port) or int(port.split("/", 1)[0]) > 65535 for port in requested):
            raise PXEFirewallError("Invalid temporary firewall port list")
        added = []
        try:
            for port in requested:
                if port not in state["ports"]:
                    self._call([f"--zone={state['zone']}", f"--add-port={port}"])
                    state["ports"].append(port)
                    added.append(port)
        except PXEFirewallError:
            for port in reversed(added):
                self._call([f"--zone={state['zone']}", f"--remove-port={port}"], check=False)
                state["ports"].remove(port)
            raise
        return tuple(added)

    def add_protocols(self, interface: str, protocols: Iterable[str]) -> tuple[str, ...]:
        """Add temporary IP protocols to an active interface-exclusive zone."""
        state = self._opened.get(interface)
        if state is None or self._current_zone(interface) != state["zone"]:
            raise PXEFirewallError("No active Feclora temporary firewall zone for interface")
        requested = list(dict.fromkeys(protocols))
        if any(not re.fullmatch(r"[a-z0-9-]{1,32}", protocol) for protocol in requested):
            raise PXEFirewallError("Invalid temporary firewall protocol list")
        state.setdefault("protocols", [])
        added = []
        try:
            for protocol in requested:
                if protocol not in state["protocols"]:
                    self._call([f"--zone={state['zone']}", f"--add-protocol={protocol}"])
                    state["protocols"].append(protocol)
                    added.append(protocol)
        except PXEFirewallError:
            for protocol in reversed(added):
                self._call([f"--zone={state['zone']}", f"--remove-protocol={protocol}"], check=False)
                state["protocols"].remove(protocol)
            raise
        return tuple(added)

    def remove_protocols(self, interface: str, protocols: Iterable[str]) -> None:
        """Remove only temporary IP protocols added for a transfer."""
        state = self._opened.get(interface)
        if state is None:
            raise PXEFirewallError("No active Feclora temporary firewall zone for interface")
        errors = []
        for protocol in dict.fromkeys(protocols):
            if protocol not in state.get("protocols", []):
                continue
            result = self._call([f"--zone={state['zone']}", f"--remove-protocol={protocol}"], check=False)
            if result.returncode != 0:
                errors.append(protocol)
            else:
                state["protocols"].remove(protocol)
        if errors:
            raise PXEFirewallError("Could not remove temporary firewall protocols: " + ", ".join(errors))

    def remove_ports(self, interface: str, ports: Iterable[str]) -> None:
        """Remove only the temporary ports added for a transfer."""
        state = self._opened.get(interface)
        if state is None:
            raise PXEFirewallError("No active Feclora temporary firewall zone for interface")
        errors = []
        for port in dict.fromkeys(ports):
            if port not in state["ports"]:
                continue
            result = self._call([f"--zone={state['zone']}", f"--remove-port={port}"], check=False)
            if result.returncode != 0:
                errors.append(port)
            else:
                state["ports"].remove(port)
        if errors:
            raise PXEFirewallError("Could not remove temporary firewall ports: " + ", ".join(errors))

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

        zone_list = self._call(["--get-zones"], check=False)
        if zone_list.returncode != 0:
            errors.append("list firewalld zones")
        elif zone in zone_list.stdout.split():
            deleted = self._call([f"--delete-zone={zone}"], check=False)
            if deleted.returncode != 0:
                errors.append(f"delete temporary zone {zone}")

        if errors:
            raise PXEFirewallError("could not restore firewalld state: " + "; ".join(errors))
        del self._opened[interface]
