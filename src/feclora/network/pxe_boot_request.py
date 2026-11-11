"""Parse identity-free PXE answer handoff parameters from the Live kernel command line.

The answer URL and job UUID are public locators, not authorization. Live must
verify the detached signature against a trust root provisioned independently
of the downloaded answer before it parses or executes any deployment action.
"""
from __future__ import annotations

import ipaddress
import shlex
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit


class PXEBootRequestError(ValueError):
    """PXE kernel handoff parameters are missing, duplicated or invalid."""


@dataclass(frozen=True)
class PXEBootRequest:
    mode: str
    job_id: str | None = None
    server_address: str | None = None
    http_port: int | None = None
    answer_url: str | None = None


def _answer_endpoint(value: str, job_id: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise PXEBootRequestError("PXE answer URL must contain a valid IPv4 listener and port") from exc
    if (parsed.scheme != "http" or address.version != 4 or address.is_unspecified
            or address.is_loopback or address.is_multicast or port is None or not 1 <= port <= 65535
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise PXEBootRequestError("PXE answer URL must be plain HTTP to a usable unicast IPv4 listener")
    if parsed.path != f"/answers/{job_id}/answer.json":
        raise PXEBootRequestError("PXE answer URL path must identify this job's answer.json")
    return str(address), port


def parse_pxe_boot_request(command_line: str) -> PXEBootRequest:
    if not isinstance(command_line, str) or len(command_line) > 65536:
        raise PXEBootRequestError("kernel command line must be text under 64 KiB")
    try:
        arguments = shlex.split(command_line, posix=True)
    except ValueError as exc:
        raise PXEBootRequestError("kernel command line contains invalid quoting") from exc
    keys = {
        "feclora.pxe_mode", "feclora.pxe_job_id", "feclora.pxe_answer_url",
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
            raise PXEBootRequestError("interactive PXE boot must not carry unattended answer parameters")
        return PXEBootRequest(mode="interactive")
    if mode != "unattended-answer":
        raise PXEBootRequestError("PXE mode must be interactive or unattended-answer")
    required = {"feclora.pxe_mode", "feclora.pxe_job_id", "feclora.pxe_answer_url"}
    if set(values) != required:
        raise PXEBootRequestError("unattended answer PXE boot requires job ID and answer URL")
    job_id = values["feclora.pxe_job_id"]
    try:
        canonical = str(uuid.UUID(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PXEBootRequestError("unattended PXE job ID must be a UUID") from exc
    if canonical != job_id:
        raise PXEBootRequestError("unattended PXE job ID must use canonical UUID notation")
    address, port = _answer_endpoint(values["feclora.pxe_answer_url"], job_id)
    return PXEBootRequest(
        mode="unattended-answer", job_id=job_id, server_address=address,
        http_port=port, answer_url=values["feclora.pxe_answer_url"],
    )
