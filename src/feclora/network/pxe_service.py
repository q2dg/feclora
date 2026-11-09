"""Explicit, transactional lifecycle for temporary PXE systemd services.

Services are never enabled at boot. start() requires successful interface and
daemon preflight plus interface-zone-scoped runtime firewall rules.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from feclora.network.pxe_config import PXENetworkConfig, render_caddy, render_dnsmasq
from feclora.network.pxe_preflight import validate_pxe_configuration
from feclora.network.firewall import PXEFirewall
from feclora.network.pxe_boot import stage_pxe_boot_tree


class PXEServiceError(RuntimeError):
    """PXE runtime services could not be started or stopped safely."""


class PXEServiceManager:
    def __init__(
        self,
        runtime_dir: str = "/run/feclora/pxe",
        *,
        runner: Callable[..., Any] = subprocess.run,
        systemd_run: str = "/usr/bin/systemd-run",
        systemctl: str = "/usr/bin/systemctl",
        dnsmasq: str = "/usr/sbin/dnsmasq",
        caddy: str = "/usr/bin/caddy",
        preflight: Callable[[PXENetworkConfig], None] = validate_pxe_configuration,
        firewall: PXEFirewall | None = None,
        boot_stager: Callable[[PXENetworkConfig], Any] = stage_pxe_boot_tree,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.runner = runner
        self.systemd_run = systemd_run
        self.systemctl = systemctl
        self.dnsmasq = dnsmasq
        self.caddy = caddy
        self.preflight = preflight
        self.firewall = firewall or PXEFirewall()
        self.boot_stager = boot_stager
        self._active_interface: str | None = None
        self._started_units: set[str] = set()
        self._dnsmasq_unit = ""
        self._caddy_unit = ""
        self._state_path = self.runtime_dir / "active.json"

    def _run(self, argv: list[str], label: str) -> None:
        try:
            self.runner(argv, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise PXEServiceError(f"{label} timed out") from exc
        except OSError as exc:
            raise PXEServiceError(f"{label} could not execute: {exc}") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise PXEServiceError(f"{label} failed: {detail or exc}") from exc

    def _assert_active(self, unit: str) -> None:
        try:
            result = self.runner(
                [self.systemctl, "is-active", unit], check=False,
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PXEServiceError(f"cannot verify {unit} startup: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stdout or result.stderr or "").strip()
            raise PXEServiceError(f"{unit} did not remain active after startup: {detail or result.returncode}")

    def _prepare_runtime(self) -> None:
        self.runtime_dir.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if self.runtime_dir.parent.is_symlink() or not self.runtime_dir.parent.is_dir():
            raise PXEServiceError("PXE runtime parent must be a real directory")
        if self.runtime_dir.parent == Path("/run/feclora"):
            parent_info = os.lstat(self.runtime_dir.parent)
            if parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
                raise PXEServiceError("PXE runtime parent must be root-owned and not group/other-writable")
            os.chmod(self.runtime_dir.parent, 0o755)
        self.runtime_dir.mkdir(mode=0o711, parents=True, exist_ok=True)
        if self.runtime_dir.is_symlink() or not self.runtime_dir.is_dir():
            raise PXEServiceError("PXE runtime path must be a real directory")
        os.chmod(self.runtime_dir, 0o711)

    def _write_config(self, name: str, content: str, mode: int = 0o600) -> str:
        destination = self.runtime_dir / name
        fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=self.runtime_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise PXEServiceError(f"cannot write PXE runtime configuration {name}: {exc}") from exc
        return str(destination)

    def _write_state(self, value: dict[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".active.", dir=self.runtime_dir)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._state_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _read_state(self) -> dict[str, Any] | None:
        try:
            info = os.lstat(self._state_path)
        except FileNotFoundError:
            return None
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 8192):
            raise PXEServiceError("persisted PXE runtime state is unsafe")
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PXEServiceError("persisted PXE runtime state is unreadable") from exc
        expected = {"schema_version", "interface", "dnsmasq_unit", "caddy_unit", "firewall"}
        if not isinstance(value, dict) or set(value) != expected or isinstance(value["schema_version"], bool) or value["schema_version"] != 1:
            raise PXEServiceError("persisted PXE runtime state has an unsupported schema")
        if not isinstance(value["interface"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", value["interface"]):
            raise PXEServiceError("persisted PXE interface is invalid")
        for key in ("dnsmasq_unit", "caddy_unit"):
            if not isinstance(value[key], str) or not re.fullmatch(r"feclora-(?:dnsmasq|caddy)-[0-9a-f]{12}", value[key]):
                raise PXEServiceError("persisted PXE systemd unit name is invalid")
        return value

    def start(self, config: PXENetworkConfig) -> None:
        """Start PXE services and persist enough state for a later API process to stop them."""
        config.validated()
        self._prepare_runtime()
        if self._read_state() is not None:
            raise PXEServiceError("PXE services already have a persisted active profile; stop it before starting another")
        # Validate interfaces and daemon prerequisites before touching the
        # published TFTP/HTTP trees. A failed preflight must have no staging
        # side effects.
        self.preflight(config)
        self.boot_stager(config)
        suffix = hashlib.sha256(config.interface.encode("ascii")).hexdigest()[:12]
        self._dnsmasq_unit = f"feclora-dnsmasq-{suffix}"
        self._caddy_unit = f"feclora-caddy-{suffix}"
        dnsmasq_config = self._write_config("dnsmasq.conf", render_dnsmasq(config))
        caddy_config = self._write_config("Caddyfile", render_caddy(config), mode=0o644)
        self._active_interface = config.interface
        try:
            self.firewall.open(
                config.interface,
                ["67/udp", "4011/udp", f"{config.http_port}/tcp"],
            )
            firewall_state = self.firewall.export_state(config.interface)
            self._write_state({
                "schema_version": 1, "interface": config.interface,
                "dnsmasq_unit": self._dnsmasq_unit, "caddy_unit": self._caddy_unit,
                "firewall": firewall_state,
            })
            self._started_units.update({self._dnsmasq_unit + ".service", self._caddy_unit + ".service"})
            self._run([
                self.systemd_run, f"--unit={self._dnsmasq_unit}", "--collect",
                "--property=Restart=no", "--property=KillMode=mixed", "--",
                self.dnsmasq, "--keep-in-foreground", f"--conf-file={dnsmasq_config}",
            ], "starting dnsmasq")
            self._assert_active(self._dnsmasq_unit + ".service")
            self._run([
                self.systemd_run, f"--unit={self._caddy_unit}", "--collect",
                "--property=Restart=no", "--property=KillMode=mixed", "--property=User=caddy", "--property=Group=caddy", "--",
                self.caddy, "run", "--config", caddy_config, "--adapter", "caddyfile",
            ], "starting Caddy")
            self._assert_active(self._caddy_unit + ".service")
        except Exception as start_error:
            try:
                self.stop()
            except PXEServiceError as rollback_error:
                raise PXEServiceError(f"{start_error}; rollback also failed: {rollback_error}") from start_error
            if isinstance(start_error, PXEServiceError):
                raise
            raise PXEServiceError(f"PXE startup failed: {start_error}") from start_error

    def status(self) -> dict[str, Any]:
        """Inspect persisted service state without changing the host."""
        saved = self._read_state()
        if saved is None:
            return {"active": False, "configured": False, "interface": None, "services": {}}
        services = {}
        for unit in (saved["dnsmasq_unit"] + ".service", saved["caddy_unit"] + ".service"):
            try:
                result = self.runner([self.systemctl, "is-active", unit], check=False,
                                     capture_output=True, text=True, timeout=10)
                services[unit] = result.stdout.strip() or "inactive"
            except (OSError, subprocess.TimeoutExpired):
                services[unit] = "unknown"
        return {
            "active": all(value == "active" for value in services.values()),
            "configured": True,
            "interface": saved["interface"],
            "services": services,
        }

    def stop(self) -> None:
        """Stop persisted transient units and restore the interface's previous firewalld zone."""
        if self._active_interface is None:
            saved = self._read_state()
            if saved is None:
                return
            self._active_interface = saved["interface"]
            self._dnsmasq_unit = saved["dnsmasq_unit"]
            self._caddy_unit = saved["caddy_unit"]
            self._started_units.update({self._dnsmasq_unit + ".service", self._caddy_unit + ".service"})
            firewall_recovery_error = None
            try:
                self.firewall.adopt(self._active_interface, saved["firewall"])
            except Exception as exc:
                # Stop daemons even if an administrator changed the interface
                # zone; firewall restoration can then be inspected separately.
                firewall_recovery_error = str(exc)
        else:
            firewall_recovery_error = None
        errors = []
        for unit in (self._caddy_unit + ".service", self._dnsmasq_unit + ".service"):
            if unit not in self._started_units:
                continue
            try:
                state = self.runner([self.systemctl, "is-active", unit], check=False,
                                    capture_output=True, text=True, timeout=15)
                if state.returncode == 0:
                    self._run([self.systemctl, "stop", unit], f"stopping {unit}")
                    self._started_units.discard(unit)
                elif state.returncode in (3, 4):
                    self._started_units.discard(unit)
                else:
                    errors.append(f"{unit}: cannot determine service state")
            except (OSError, subprocess.TimeoutExpired, PXEServiceError) as exc:
                errors.append(f"{unit}: {exc}")
        if self._active_interface is not None and not self._started_units:
            if firewall_recovery_error is not None:
                errors.append(f"firewall recovery: {firewall_recovery_error}")
            else:
                try:
                    self.firewall.close(self._active_interface)
                    self._active_interface = None
                except Exception as exc:
                    errors.append(f"firewall: {exc}")
        if errors:
            raise PXEServiceError("failed to stop PXE runtime cleanly: " + "; ".join(errors))
        if self._active_interface is None:
            try:
                self._state_path.unlink()
            except FileNotFoundError:
                pass
            for name in ("dnsmasq.conf", "Caddyfile"):
                try:
                    (self.runtime_dir / name).unlink()
                except FileNotFoundError:
                    pass
