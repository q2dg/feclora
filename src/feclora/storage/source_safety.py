"""Fail-closed checks that a capture source is not mounted or the live root disk."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .system_protection import collect_root_backing_disks


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
    swaps_path: str = "/proc/swaps",
    stat_device: Callable[[str], Any] | None = None,
    effective_uid: Callable[[], int] | None = None,
) -> None:
    """Reject mounted source trees and any source backing the live root."""
    if not isinstance(source_path, str) or not source_path.startswith("/dev/"):
        raise SourceSafetyError("capture source must be a /dev/ path")
    run = runner or subprocess.run
    resolve = which or shutil.which
    lsblk, fuser = resolve("lsblk"), resolve("fuser")
    if not lsblk or not fuser:
        raise SourceSafetyError("lsblk and fuser are required for capture source safety checks")
    uid = (effective_uid or os.geteuid)()
    if uid != 0:
        sudo = resolve("sudo")
        if not sudo:
            raise SourceSafetyError("sudo is required to inspect block-device users")
        try:
            privilege_check = run(
                [sudo, "-n", "true"], check=False, capture_output=True,
                text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceSafetyError(f"cannot verify non-interactive root privileges: {exc}") from exc
        if privilege_check.returncode != 0:
            raise SourceSafetyError("non-interactive root privileges are unavailable")
    try:
        result = run(
            [lsblk, "--json", "--tree", "--paths", "--output", "PATH,TYPE,MOUNTPOINTS", source_path],
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
    device_paths = {
        node["path"] for node in _walk(tree)
        if isinstance(node.get("path"), str) and node["path"].startswith("/dev/")
    }
    # Active swap is not necessarily represented as a mountpoint in lsblk.
    try:
        with open(swaps_path, "r", encoding="utf-8") as swaps:
            next(swaps, None)
            for line in swaps:
                fields = line.split()
                if fields and fields[0].startswith("/dev/"):
                    if os.path.realpath(fields[0]) in {os.path.realpath(p) for p in device_paths}:
                        raise SourceSafetyError(f"capture source is active swap: {fields[0]}")
    except FileNotFoundError as exc:
        raise SourceSafetyError("cannot inspect active swap devices") from exc
    # fuser detects processes holding the block device open, not just mounts.
    for device_path in sorted(device_paths):
        try:
            fuser_command = privileged_argv([fuser, "-s", device_path], effective_uid=lambda: uid, which=resolve)
            busy = run(fuser_command, check=False, capture_output=True,
                       text=True, timeout=15)
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise SourceSafetyError(f"cannot check processes using {device_path}: {exc}") from exc
        if busy.returncode == 0:
            raise SourceSafetyError(f"capture source is open by a process: {device_path}")
        if busy.returncode != 1:
            raise SourceSafetyError(f"fuser could not verify whether {device_path} is busy")
        try:
            info = (stat_device or os.stat)(device_path)
            if stat.S_ISBLK(info.st_mode):
                holders = f"/sys/dev/block/{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}/holders"
                if not os.path.isdir(holders):
                    raise SourceSafetyError(f"cannot inspect device-mapper holders for {device_path}")
                if os.listdir(holders):
                    raise SourceSafetyError(f"capture source has active device-mapper holders: {device_path}")
        except OSError as exc:
            raise SourceSafetyError(f"cannot inspect block-device holders for {device_path}: {exc}") from exc
    try:
        inverse = run(
            [lsblk, "--json", "--tree", "--paths", "--inverse", "--output", "PATH,TYPE", source_path],
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
