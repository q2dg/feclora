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
    disks: set[str] = set()
    if not isinstance(source, str):
        raise SystemProtectionError("Cannot identify the live root mount source")
    if source.startswith("/dev/"):
        graph = _run_json(
            [lsblk, "--json", "--tree", "--paths", "--inverse", "--output", "PATH,TYPE", source],
            run,
        )
        roots = graph.get("blockdevices")
        if not isinstance(roots, list):
            raise SystemProtectionError("lsblk did not return a dependency graph")
        graphs = [roots]
    else:
        # Live systems commonly mount an overlay/squashfs root whose SOURCE is
        # not a block node. Conservatively protect every physical disk backing
        # any currently mounted block device (including the Live boot medium).
        graph = _run_json(
            [lsblk, "--json", "--tree", "--paths", "--output", "PATH,TYPE,MOUNTPOINTS"],
            run,
        )
        roots = graph.get("blockdevices")
        if not isinstance(roots, list):
            raise SystemProtectionError("lsblk did not return the mounted-device tree")
        mounted_paths: list[str] = []
        def collect_mounted(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                mountpoints = node.get("mountpoints") or []
                if isinstance(mountpoints, str):
                    mountpoints = [mountpoints]
                if mountpoints and isinstance(node.get("path"), str):
                    mounted_paths.append(node["path"])
                children = node.get("children")
                if isinstance(children, list):
                    collect_mounted(children)
        collect_mounted(roots)
        if not mounted_paths:
            raise SystemProtectionError(
                f"Root source {source!r} is not a block node and no mounted backing devices can be identified"
            )
        graphs = []
        for mounted_path in mounted_paths:
            inverse = _run_json(
                [lsblk, "--json", "--tree", "--paths", "--inverse", "--output", "PATH,TYPE", mounted_path],
                run,
            )
            dependencies = inverse.get("blockdevices")
            if not isinstance(dependencies, list):
                raise SystemProtectionError(f"Cannot trace mounted device {mounted_path}")
            graphs.append(dependencies)
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
    for graph_roots in graphs:
        visit(graph_roots)
    if not disks and source.startswith("/dev/"):
        # A /dev root can still be a loop or Live mapper device. Fall back to
        # the mounted-device graph so the backing Live medium is protected.
        mounted_graph = _run_json(
            [lsblk, "--json", "--tree", "--paths", "--output", "PATH,TYPE,MOUNTPOINTS"],
            run,
        )
        mounted_roots = mounted_graph.get("blockdevices")
        if not isinstance(mounted_roots, list):
            raise SystemProtectionError("Cannot inspect mounted devices backing the Live root")
        mounted_paths: list[str] = []
        def collect_mounts(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                points = node.get("mountpoints") or []
                if isinstance(points, str):
                    points = [points]
                if points and isinstance(node.get("path"), str):
                    mounted_paths.append(node["path"])
                children = node.get("children")
                if isinstance(children, list):
                    collect_mounts(children)
        collect_mounts(mounted_roots)
        for mounted_path in mounted_paths:
            inverse = _run_json(
                [lsblk, "--json", "--tree", "--paths", "--inverse", "--output", "PATH,TYPE", mounted_path],
                run,
            )
            dependencies = inverse.get("blockdevices")
            if not isinstance(dependencies, list):
                raise SystemProtectionError(f"Cannot trace mounted device {mounted_path}")
            visit(dependencies)
    if not disks:
        raise SystemProtectionError(
            f"Could not resolve the backing disk(s) for live root source {source}"
        )
    return disks
