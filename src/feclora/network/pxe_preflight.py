"""Pre-activation validation for generated dnsmasq and Caddy configuration."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from feclora.network.interface_discovery import (
    discover_interface_addresses,
    validate_selected_address,
)
from feclora.network.pxe_config import (
    PXENetworkConfig,
    render_caddy,
    render_dnsmasq,
)


class PXEPreflightError(RuntimeError):
    """A generated PXE configuration failed pre-activation validation."""


def validate_pxe_configuration(
    config: PXENetworkConfig,
    *,
    dnsmasq: str | None = None,
    caddy: str | None = None,
    ip: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
    temp_parent: str | None = None,
    address_discovery: Callable[..., list[Any]] = discover_interface_addresses,
) -> None:
    """Validate live interface binding and both daemon configs; start no service."""
    config.validated()
    dnsmasq_bin = dnsmasq or shutil.which("dnsmasq")
    caddy_bin = caddy or shutil.which("caddy")
    if not dnsmasq_bin or not caddy_bin:
        raise PXEPreflightError("dnsmasq and caddy are required for PXE preflight")
    try:
        addresses = address_discovery(config.interface, executable=ip)
        validate_selected_address(
            config.interface, config.address, config.prefix_length, addresses,
        )
    except Exception as exc:
        raise PXEPreflightError(f"PXE interface/address validation failed: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="feclora-pxe-check-", dir=temp_parent) as directory:
        root = Path(directory)
        dnsmasq_file = root / "dnsmasq.conf"
        caddy_file = root / "Caddyfile"
        dnsmasq_file.write_text(render_dnsmasq(config), encoding="utf-8")
        caddy_file.write_text(render_caddy(config), encoding="utf-8")
        commands = (
            ([dnsmasq_bin, "--test", f"--conf-file={dnsmasq_file}"], "dnsmasq"),
            ([caddy_bin, "validate", "--config", str(caddy_file), "--adapter", "caddyfile"], "Caddy"),
        )
        for argv, label in commands:
            try:
                runner(
                    argv, check=True, capture_output=True, text=True, timeout=20,
                )
            except subprocess.TimeoutExpired as exc:
                raise PXEPreflightError(f"{label} configuration validation timed out") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()
                raise PXEPreflightError(
                    f"{label} rejected the generated configuration: {detail or exc}"
                ) from exc
