"""Explicit, transactional lifecycle for temporary PXE systemd services.

Services are never enabled at boot. start() requires successful interface and
daemon preflight plus interface-zone-scoped runtime firewall rules.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
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
        suffix = uuid.uuid4().hex
        self._dnsmasq_unit = f"feclora-dnsmasq-{suffix}"
        self._caddy_unit = f"feclora-caddy-{suffix}"

    def _run(self, argv: list[str], label: str) -> None:
        try:
            self.runner(argv, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise PXEServiceError(f"{label} timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise PXEServiceError(f"{label} failed: {detail or exc}") from exc

    def _prepare_runtime(self) -> None:
        self.runtime_dir.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if self.runtime_dir.parent.is_symlink() or not self.runtime_dir.parent.is_dir():
            raise PXEServiceError("PXE runtime parent must be a real directory")
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

    def start(self, config: PXENetworkConfig) -> None:
        """Start dnsmasq then Caddy; roll back services and firewall on failure."""
        config.validated()
        self.boot_stager(config)
        self.preflight(config)
        self._prepare_runtime()
        dnsmasq_config = self._write_config("dnsmasq.conf", render_dnsmasq(config))
        caddy_config = self._write_config("Caddyfile", render_caddy(config), mode=0o644)
        self._active_interface = config.interface
        try:
            self.firewall.open(
                config.interface,
                ["67/udp", "4011/udp", f"{config.http_port}/tcp"],
            )
            self._started_units.add(self._dnsmasq_unit + ".service")
            self._run([
                self.systemd_run, f"--unit={self._dnsmasq_unit}", "--collect",
                "--property=Restart=no", "--property=KillMode=mixed", "--",
                self.dnsmasq, "--keep-in-foreground", f"--conf-file={dnsmasq_config}",
            ], "starting dnsmasq")
            self._started_units.add(self._caddy_unit + ".service")
            self._run([
                self.systemd_run, f"--unit={self._caddy_unit}", "--collect",
                "--property=Restart=no", "--property=KillMode=mixed", "--property=User=caddy", "--property=Group=caddy", "--",
                self.caddy, "run", "--config", caddy_config, "--adapter", "caddyfile",
            ], "starting Caddy")
        except Exception as start_error:
            try:
                self.stop()
            except PXEServiceError as rollback_error:
                raise PXEServiceError(
                    f"{start_error}; rollback also failed: {rollback_error}"
                ) from start_error
            if isinstance(start_error, PXEServiceError):
                raise
            raise PXEServiceError(f"PXE startup failed: {start_error}") from start_error

    def stop(self) -> None:
        """Stop active transient units and remove only firewall ports we added."""
        errors = []
        for unit in (self._caddy_unit + ".service", self._dnsmasq_unit + ".service"):
            if unit not in self._started_units:
                continue
            try:
                state = self.runner(
                    [self.systemctl, "is-active", unit], check=False,
                    capture_output=True, text=True, timeout=15,
                )
                if state.returncode == 0:
                    self._run([self.systemctl, "stop", unit], f"stopping {unit}")
                    self._started_units.discard(unit)
                elif state.returncode in (3, 4):
                    self._started_units.discard(unit)
                else:
                    errors.append(f"{unit}: cannot determine service state")
            except (OSError, subprocess.TimeoutExpired, PXEServiceError) as exc:
                errors.append(f"{unit}: {exc}")
        if self._active_interface is not None:
            try:
                self.firewall.close(self._active_interface)
                self._active_interface = None
            except Exception as exc:
                errors.append(f"firewall: {exc}")
        if errors:
            raise PXEServiceError("failed to stop PXE runtime cleanly: " + "; ".join(errors))
