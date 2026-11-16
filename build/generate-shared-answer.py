#!/usr/bin/env python3
"""Generate one canonical schema-v1 unattended answer for a Client fleet."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from feclora.deployment.job import DeploymentJob, JobValidationError


class AnswerGenerationError(ValueError):
    """The shared deployment answer cannot be generated safely."""


def _parse_binding(value: str) -> tuple[str, dict[str, str | None]]:
    if "=" not in value:
        raise AnswerGenerationError("each --client must use MAC=WWN|SERIAL")
    mac, selectors = value.split("=", 1)
    if "|" not in selectors:
        raise AnswerGenerationError("each --client must use MAC=WWN|SERIAL")
    wwn, serial = selectors.split("|", 1)
    if not wwn and not serial:
        raise AnswerGenerationError("each Client requires a WWN, serial, or both")
    return mac, {"wwn": wwn or None, "serial": serial or None}


def build_shared_answer(
    *,
    image_id: str,
    repository_id: str,
    clients: list[str],
    network_interface: str,
    transport: str = "multicast",
    multicast_group: str | None = "239.10.10.10",
    multicast_port: int | None = 9000,
    boot_method: str = "iso",
    job_id: str | None = None,
) -> str:
    """Validate fleet inputs and return the one canonical shared answer."""
    bindings: dict[str, dict[str, str | None]] = {}
    macs: list[str] = []
    for entry in clients:
        mac, binding = _parse_binding(entry)
        macs.append(mac)
        bindings[mac] = binding
    if transport == "multicast" and len(macs) < 2:
        raise AnswerGenerationError("multicast requires at least two authorized Clients")
    payload = {
        "schema_version": 1,
        "job_id": job_id or str(uuid4()),
        "operation": "restore",
        "image_id": image_id,
        "target_type": "disk",
        "authorized_clients": macs,
        "network_interface": "auto" if boot_method == "pxe" else network_interface,
        "boot_method": boot_method,
        "transport": transport,
        "multicast_group": multicast_group if transport == "multicast" else None,
        "multicast_port": multicast_port if transport == "multicast" else None,
        "start_policy": "automatic",
        "repository_id": repository_id,
        "target_bindings": bindings,
        "confirm_destructive": True,
    }
    try:
        job = DeploymentJob.from_dict(payload)
    except JobValidationError as exc:
        raise AnswerGenerationError(str(exc)) from exc
    return job.to_json() + "\n"


def write_shared_answer(document: str, output: str) -> None:
    """Create the answer atomically without replacing an existing file."""
    destination = Path(output)
    if not destination.is_absolute() or not destination.parent.is_dir() or destination.parent.is_symlink():
        raise AnswerGenerationError("output must be an absolute path in an existing real directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(destination, flags, 0o600)
    except FileExistsError as exc:
        raise AnswerGenerationError("output already exists; refusing to overwrite") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--client", action="append", required=True,
                        help="one authorized Client binding: MAC=WWN|SERIAL (either selector may be empty)")
    parser.add_argument("--network-interface", default="enp2s0",
                        help="Server/Live interface for ISO or USB boot (default: enp2s0)")
    parser.add_argument("--transport", choices=("multicast", "unicast"), default="multicast")
    parser.add_argument("--multicast-group", default="239.10.10.10")
    parser.add_argument("--multicast-port", type=int, default=9000)
    parser.add_argument("--boot-method", choices=("iso", "pxe"), default="iso")
    parser.add_argument("--output", required=True, help="new shared answer JSON path; never overwritten")
    args = parser.parse_args()
    try:
        document = build_shared_answer(
            image_id=args.image_id, repository_id=args.repository_id,
            clients=args.client, network_interface=args.network_interface,
            transport=args.transport,
            multicast_group=args.multicast_group,
            multicast_port=args.multicast_port,
            boot_method=args.boot_method,
        )
        write_shared_answer(document, args.output)
    except (AnswerGenerationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    job = json.loads(document)
    print(json.dumps({
        "output": args.output, "job_id": job["job_id"],
        "authorized_clients": len(job["authorized_clients"]),
        "transport": job["transport"], "boot_method": args.boot_method,
    }, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
