"""Automatic Client startup for an explicitly job-bound PXE Live boot."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from feclora.deployment.client_service import (
    ClientJobServiceError, _ensure_directory, _job_paths, _write_private_json,
)
from feclora.deployment.runtime_config import load_client_runtime_config
from feclora.network.pxe_boot_request import PXEBootRequestError, parse_pxe_boot_request


CLIENT_CONFIG = "/mnt/feclora-pxe-identity/feclora-client-identity/deployment-client.json"


def start_unattended_pxe_client(
    *,
    command_line_path: str = "/proc/cmdline",
    config_path: str = CLIENT_CONFIG,
    runner=None,
) -> str | None:
    """Create a constrained restore request and start its per-job Client unit."""
    try:
        command_line = Path(command_line_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ClientJobServiceError(f"cannot read PXE kernel command line: {exc}") from exc
    try:
        handoff = parse_pxe_boot_request(command_line)
    except PXEBootRequestError as exc:
        raise ClientJobServiceError(f"invalid PXE handoff: {exc}") from exc
    if handoff.mode != "unattended":
        return None
    if not handoff.job_id or not handoff.server_address or not handoff.control_port:
        raise ClientJobServiceError("unattended PXE handoff is incomplete")
    runner = runner or subprocess.run
    try:
        runner(
            ["/usr/bin/systemctl", "start", "mnt-feclora\\x2dpxe\\x2didentity.mount"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, check=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClientJobServiceError(f"could not mount the dedicated PXE Client identity medium: {exc}") from exc
    config = load_client_runtime_config(config_path)
    _ensure_directory()
    request_path, status_path, _lock_path = _job_paths(handoff.job_id)
    if os.path.lexists(request_path) or os.path.lexists(status_path):
        raise ClientJobServiceError("this PXE job already has a local request or status record")
    request = {
        "schema_version": 1,
        "job_id": handoff.job_id,
        "host": handoff.server_address,
        "port": handoff.control_port,
        "device_path": None,
        "confirmation": None,
        "compression": "none",
        "network_interface": None,
        "igmp_confirmed": False,
        "image_encrypt": False,
        "image_sign": False,
        "unattended": True,
    }
    _write_private_json(request_path, request)
    try:
        runner(
            ["/usr/bin/systemctl", "start", "--no-block",
             f"feclora-pxe-client@{handoff.job_id}.service"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, check=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            request_path.unlink()
        except OSError:
            pass
        raise ClientJobServiceError(f"could not start authenticated PXE Client job: {exc}") from exc
    return handoff.job_id


def main() -> int:
    try:
        job_id = start_unattended_pxe_client()
    except Exception as exc:
        print(f"feclora PXE Client startup: {exc}", file=sys.stderr)
        return 1
    if job_id is not None:
        print(f"Feclora PXE Client job {job_id} started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
