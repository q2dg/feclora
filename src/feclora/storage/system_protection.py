"""Resolve the backing disks of the live root filesystem using findmnt/lsblk.

The probe is read-only and fails closed when the root mount cannot be traced to
one or more whole disks.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from typing import Any, Callable

class SystemProtectionError(RuntimeError):
    """The live root backing devices cannot be identified safely."""

def _run_json(command: list[str], runner: Callable[..., Any]) -> dict[str, Any]:
    try:
        result = runner(command, check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemProtectionError(f"Unable to inspect system storage: {exc}") from exc
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SystemProtectionError("Storage inspection returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SystemProtectionError("Storage inspection returned an invalid document")
    return payload

def collect_root_backing_disks(
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> set[str]:
    """Trace findmnt's root source through lsblk inverse dependencies to disks."""
    run = runner or subprocess.run
    resolve = which or shutil.which
    findmnt, lsblk = resolve("findmnt"), resolve("lsblk")
    if not findmnt or not lsblk:
        raise SystemProtectionError("Both findmnt and lsblk are required")
    mounts = _run_json(
        [findmnt, "--json", "--target", "/", "--output", "SOURCE"], run
    )
    filesystems = mounts.get("filesystems")
    if not isinstance(filesystems, list) or len(filesystems) != 1:
        raise SystemProtectionError("Cannot uniquely identify the live root mount")
    item = filesystems[0]
    source = item.get("source") if isinstance(item, dict) else None
    if not isinstance(source, str) or not source.startswith("/dev/"):
        raise SystemProtectionError(
            f"Live root source is not a resolvable block-device path: {source!r}"
        )
    graph = _run_json(
        [lsblk, "--json", "--tree", "--paths", "--inverse", "--output", "PATH,TYPE", source],
        run,
    )
    roots = graph.get("blockdevices")
    if not isinstance(roots, list):
        raise SystemProtectionError("lsblk did not return a dependency graph")
    disks: set[str] = set()
    def visit(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "disk":
                path = node.get("path")
                if isinstance(path, str) and path.startswith("/dev/"):
                    disks.add(path)
            children = node.get("children")
            if isinstance(children, list):
                visit(children)
    visit(roots)
    if not disks:
        raise SystemProtectionError(
            f"Could not resolve the backing disk(s) for live root source {source}"
        )
    return disks
