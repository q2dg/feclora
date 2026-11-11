"""Parse non-secret PXE handoff parameters from the Live kernel command line.

These values identify a requested mode and job only. They never authorize a
storage operation; unattended clients must still authenticate and obtain a
currently authorized job over the TLS 1.3 mutual-authenticated control plane.
"""
from __future__ import annotations

import ipaddress
import shlex
import uuid
from dataclasses import dataclass


class PXEBootRequestError(ValueError):
    """PXE kernel handoff parameters are missing, duplicated or invalid."""


@dataclass(frozen=True)
class PXEBootRequest:
    mode: str
    job_id: str | None = None
    server_address: str | None = None
    control_port: int | None = None


def parse_pxe_boot_request(command_line: str) -> PXEBootRequest:
    if not isinstance(command_line, str) or len(command_line) > 65536:
        raise PXEBootRequestError("kernel command line must be text under 64 KiB")
    try:
        arguments = shlex.split(command_line, posix=True)
    except ValueError as exc:
        raise PXEBootRequestError("kernel command line contains invalid quoting") from exc
    keys = {
        "feclora.pxe_mode", "feclora.pxe_job_id",
        "feclora.pxe_server", "feclora.pxe_control_port",
    }
    values: dict[str, str] = {}
    for argument in arguments:
        if "=" not in argument:
            continue
        key, value = argument.split("=", 1)
        if key not in keys:
            continue
        if key in values:
            raise PXEBootRequestError(f"duplicate PXE handoff parameter: {key}")
        if not value or any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise PXEBootRequestError(f"invalid PXE handoff value: {key}")
        values[key] = value

    mode = values.get("feclora.pxe_mode", "interactive")
    if mode == "interactive":
        if any(key in values for key in keys - {"feclora.pxe_mode"}):
            raise PXEBootRequestError("interactive PXE boot must not carry unattended job parameters")
        return PXEBootRequest(mode="interactive")
    if mode != "unattended":
        raise PXEBootRequestError("PXE mode must be interactive or unattended")

    required = {
        "feclora.pxe_mode", "feclora.pxe_job_id",
        "feclora.pxe_server", "feclora.pxe_control_port",
    }
    if set(values) != required:
        raise PXEBootRequestError("unattended PXE boot requires job ID, Server address and control port")
    job_id = values["feclora.pxe_job_id"]
    try:
        canonical = str(uuid.UUID(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PXEBootRequestError("unattended PXE job ID must be a UUID") from exc
    if canonical != job_id:
        raise PXEBootRequestError("unattended PXE job ID must use canonical UUID notation")
    try:
        address = ipaddress.ip_address(values["feclora.pxe_server"])
    except ValueError as exc:
        raise PXEBootRequestError("PXE Server address must be IPv4") from exc
    if address.version != 4 or address.is_unspecified or address.is_loopback or address.is_multicast:
        raise PXEBootRequestError("PXE Server address must be usable unicast IPv4")
    try:
        port = int(values["feclora.pxe_control_port"], 10)
    except ValueError as exc:
        raise PXEBootRequestError("PXE control port must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise PXEBootRequestError("PXE control port must be between 1024 and 65535")
    return PXEBootRequest(
        mode="unattended", job_id=job_id,
        server_address=str(address), control_port=port,
    )
