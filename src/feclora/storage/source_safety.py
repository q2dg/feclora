"""Fail-closed checks that a capture source is not mounted or the live root disk."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Callable

from .system_protection import SystemProtectionError, collect_root_backing_disks


class SourceSafetyError(RuntimeError):
    """The source device is mounted, system-critical, or cannot be verified."""


def _decode_tree(output: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SourceSafetyError("lsblk returned invalid source safety JSON") from exc
    devices = payload.get("blockdevices") if isinstance(payload, dict) else None
    if not isinstance(devices, list) or not devices:
        raise SourceSafetyError("lsblk could not resolve the capture source")
    return devices


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        if not isinstance(node, dict):
            raise SourceSafetyError("lsblk returned an invalid device tree")
        yield node
        children = node.get("children") or []
        if not isinstance(children, list):
            raise SourceSafetyError("lsblk returned invalid child devices")
        yield from _walk(children)


def check_capture_source_safe(
    source_path: str,
    *,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    root_disk_resolver: Callable[..., set[str]] | None = None,
) -> None:
    """Reject mounted source trees and any source backing the live root."""
    if not isinstance(source_path, str) or not source_path.startswith("/dev/"):
        raise SourceSafetyError("capture source must be a /dev/ path")
    run = runner or subprocess.run
    resolve = which or shutil.which
    lsblk = resolve("lsblk")
    if not lsblk:
        raise SourceSafetyError("lsblk is required for capture source safety checks")
    try:
        result = run(
            [lsblk, "--json", "--paths", "--output", "PATH,TYPE,MOUNTPOINTS", source_path],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceSafetyError(f"cannot inspect capture source: {exc}") from exc
    tree = _decode_tree(result.stdout)
    mounted = []
    for node in _walk(tree):
        mountpoints = node.get("mountpoints") or []
        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]
        if not isinstance(mountpoints, list):
            raise SourceSafetyError("lsblk returned invalid mountpoint metadata")
        mounted.extend(str(point) for point in mountpoints if point)
    if mounted:
        raise SourceSafetyError(
            "capture source has mounted filesystems: " + ", ".join(sorted(set(mounted)))
        )
    try:
        inverse = run(
            [lsblk, "--json", "--paths", "--inverse", "--output", "PATH,TYPE", source_path],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceSafetyError(f"cannot trace capture source to parent disks: {exc}") from exc
    disk_paths = {
        node["path"] for node in _walk(_decode_tree(inverse.stdout))
        if node.get("type") == "disk" and isinstance(node.get("path"), str)
    }
    resolver = root_disk_resolver or collect_root_backing_disks
    try:
        protected = resolver(runner=run, which=resolve)
    except Exception as exc:
        raise SourceSafetyError(f"cannot verify live root backing disks: {exc}") from exc
    if disk_paths & protected or source_path in protected:
        raise SourceSafetyError("capture source backs the live system root")
