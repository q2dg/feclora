"""Read-only Stratis filesystem and backing-device discovery.

Active Stratis filesystems are exposed below /dev/stratis. Their device-mapper
slaves are followed through sysfs to identify physical backing block devices.
No pool activation, daemon start, mount, or metadata mutation is performed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
import shutil
import subprocess

from .stratis_cli_inventory import parse_pool_list, parse_filesystem_list


class StratisInventoryError(RuntimeError):
    """Stratis device links or sysfs topology could not be read safely."""


def _leaf_slaves(block_name: str, sys_class_block: Path, seen: set[str]) -> list[str]:
    if block_name in seen:
        return []
    seen.add(block_name)
    slaves = sys_class_block / block_name / "slaves"
    try:
        entries = sorted(slaves.iterdir())
    except FileNotFoundError:
        if block_name.startswith("dm-"):
            raise StratisInventoryError(f"device-mapper topology is missing for {block_name}")
        return [block_name]
    except OSError as exc:
        raise StratisInventoryError(f"cannot inspect sysfs slaves for {block_name}: {exc}") from exc
    if not entries:
        if block_name.startswith("dm-"):
            raise StratisInventoryError(f"device-mapper node has no backing slaves: {block_name}")
        return [block_name]
    result: list[str] = []
    for entry in entries:
        result.extend(_leaf_slaves(entry.name, sys_class_block, seen))
    return result


def collect_stratis_topology(
    dev_root: str = "/dev/stratis",
    sys_class_block: str = "/sys/class/block",
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Enumerate active Stratis filesystems and their sysfs backing devices."""
    root = Path(dev_root)
    if not root.exists():
        return {"status": "unavailable", "pools": []}
    if not root.is_dir():
        raise StratisInventoryError("Stratis device root is not a directory")
    executable = which("stratis")
    if executable is None:
        return {"status": "metadata_unavailable", "pools": []}
    try:
        pool_output = runner([executable, "pool"], check=True, capture_output=True, text=True, timeout=20)
        filesystem_output = runner([executable, "filesystem"], check=True, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired as exc:
        raise StratisInventoryError("stratis CLI timed out while reading topology") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise StratisInventoryError(f"stratis CLI failed: {detail or exc}") from exc
    except OSError as exc:
        raise StratisInventoryError(f"cannot execute stratis CLI: {exc}") from exc
    pool_metadata = parse_pool_list(pool_output.stdout)
    filesystem_metadata = parse_filesystem_list(filesystem_output.stdout)
    pools: list[dict[str, Any]] = []
    try:
        pool_entries = sorted(root.iterdir())
    except OSError as exc:
        raise StratisInventoryError(f"cannot enumerate Stratis device root: {exc}") from exc
    for pool_entry in pool_entries:
        if not pool_entry.is_dir():
            continue
        filesystems = []
        try:
            fs_entries = sorted(pool_entry.iterdir())
        except OSError as exc:
            raise StratisInventoryError(f"cannot enumerate Stratis pool {pool_entry.name}: {exc}") from exc
        for fs_entry in fs_entries:
            if not fs_entry.is_symlink():
                continue
            try:
                resolved = Path(os.path.realpath(fs_entry))
            except OSError as exc:
                raise StratisInventoryError(f"cannot resolve Stratis filesystem {fs_entry}: {exc}") from exc
            if resolved.parent != Path("/dev") or not resolved.name.startswith("dm-"):
                raise StratisInventoryError(
                    f"Stratis filesystem link does not resolve to a device-mapper node: {fs_entry}"
                )
            dm_name = resolved.name
            backing = _leaf_slaves(dm_name, Path(sys_class_block), set())
            metadata = filesystem_metadata.get((pool_entry.name, fs_entry.name), {})
            filesystems.append({
                "name": fs_entry.name,
                "device": str(fs_entry),
                "mapper_device": str(resolved),
                "backing_block_devices": backing,
                "backing_device_paths": ["/dev/" + name for name in backing],
                **metadata,
            })
        pools.append({
            "name": pool_entry.name,
            "filesystems": filesystems,
            **pool_metadata.get(pool_entry.name, {}),
        })
    # Inventory completeness is about identity and geometry, not health.
    # Require metadata for every active pool and filesystem; an empty filesystem
    # list must not make all() silently turn a partial inventory into "available".
    complete = bool(pools) and all(
        pool.get("uuid")
        and pool.get("total_physical_bytes") is not None
        and pool.get("free_physical_bytes") is not None
        and all(
            fs.get("uuid") and fs.get("logical_size_bytes") is not None
            for fs in pool["filesystems"]
        )
        for pool in pools
    )
    return {"status": "available" if complete else "metadata_incomplete", "pools": pools}
