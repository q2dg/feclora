"""Explicit, transactional lifecycle for temporary PXE systemd services.

Services are never enabled at boot. start() requires successful interface and
daemon preflight plus interface-zone-scoped runtime firewall rules.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from feclora.network.pxe_config import PXENetworkConfig, render_caddy, render_dnsmasq
from feclora.network.pxe_preflight import validate_pxe_configuration
from feclora.network.firewall import PXEFirewall


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
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.runner = runner
        self.systemd_run = systemd_run
        self.systemctl = systemctl
        self.dnsmasq = dnsmasq
        self.caddy = caddy
        self.preflight = preflight
        self.firewall = firewall or PXEFirewall()
        self._active_interface: str | None = None

    def _run(self, argv: list[str], label: str) -> None:
        try:
            self.runner(argv, check=True, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise PXEServiceError(f"{label} timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise PXEServiceError(f"{label} failed: {detail or exc}") from exc

    def _prepare_runtime(self) -> None:
        self.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.runtime_dir.is_symlink() or not self.runtime_dir.is_dir():
            raise PXEServiceError("PXE runtime path must be a real directory")
        os.chmod(self.runtime_dir, 0o700)

    def _write_config(self, name: str, content: str) -> str:
        destination = self.runtime_dir / name
        fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=self.runtime_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
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
        self.preflight(config)
        self._prepare_runtime()
        dnsmasq_config = self._write_config("dnsmasq.conf", render_dnsmasq(config))
        caddy_config = self._write_config("Caddyfile", render_caddy(config))
        self.firewall.open(
            config.interface,
            ["67/udp", "69/udp", "4011/udp", f"{config.http_port}/tcp"],
        )
        self._active_interface = config.interface
        try:
            self._run([
                self.systemd_run, "--unit=feclora-dnsmasq", "--collect",
                "--property=Restart=no", "--property=KillMode=mixed", "--",
                self.dnsmasq, "--keep-in-foreground", f"--conf-file={dnsmasq_config}",
            ], "starting dnsmasq")
            self._run([
                self.systemd_run, "--unit=feclora-caddy", "--collect",
                "--property=Restart=no", "--property=KillMode=mixed", "--",
                self.caddy, "run", "--config", caddy_config, "--adapter", "caddyfile",
            ], "starting Caddy")
        except PXEServiceError:
            self.stop()
            raise

    def stop(self) -> None:
        """Stop active transient units and remove only firewall ports we added."""
        errors = []
        for unit in ("feclora-caddy.service", "feclora-dnsmasq.service"):
            try:
                state = self.runner(
                    [self.systemctl, "is-active", unit], check=False,
                    capture_output=True, text=True, timeout=15,
                )
                if state.returncode == 0:
                    self._run([self.systemctl, "stop", unit], f"stopping {unit}")
                elif state.returncode not in (3, 4):
                    errors.append(f"{unit}: cannot determine service state")
            except (OSError, subprocess.TimeoutExpired, PXEServiceError) as exc:
                errors.append(f"{unit}: {exc}")
        if self._active_interface is not None:
            try:
                self.firewall.close(self._active_interface)
            except Exception as exc:
                errors.append(f"firewall: {exc}")
            self._active_interface = None
        if errors:
            raise PXEServiceError("failed to stop PXE runtime cleanly: " + "; ".join(errors))
