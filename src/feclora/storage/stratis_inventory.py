"""Read-only Stratis filesystem and backing-device discovery.

Active Stratis filesystems are exposed below /dev/stratis. Their device-mapper
slaves are followed through sysfs to identify physical backing block devices.
No pool activation, daemon start, mount, or metadata mutation is performed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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
        return [block_name]
    except OSError as exc:
        raise StratisInventoryError(f"cannot inspect sysfs slaves for {block_name}: {exc}") from exc
    if not entries:
        return [block_name]
    result: list[str] = []
    for entry in entries:
        result.extend(_leaf_slaves(entry.name, sys_class_block, seen))
    return result


def collect_stratis_topology(
    dev_root: str = "/dev/stratis",
    sys_class_block: str = "/sys/class/block",
) -> dict[str, Any]:
    """Enumerate active Stratis filesystems and their sysfs backing devices."""
    root = Path(dev_root)
    if not root.exists():
        return {"status": "unavailable", "pools": []}
    if not root.is_dir():
        raise StratisInventoryError("Stratis device root is not a directory")
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
            dm_name = resolved.name
            backing = _leaf_slaves(dm_name, Path(sys_class_block), set())
            filesystems.append({
                "name": fs_entry.name,
                "device": str(fs_entry),
                "mapper_device": str(resolved),
                "backing_block_devices": backing,
            })
        pools.append({"name": pool_entry.name, "filesystems": filesystems})
    return {"status": "available", "pools": pools}
