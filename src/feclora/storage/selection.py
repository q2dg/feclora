"""Non-destructive validation for whole-disk clone selections.

This module builds a plan only. It never opens block devices or performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


class SelectionError(ValueError):
    """Raised when a source/target pair is unsafe or ambiguous."""


@dataclass(frozen=True)
class CloneSelection:
    """Validated whole-disk selection; this object is not an execution request."""

    source_path: str
    target_path: str
    source_size_bytes: int
    target_size_bytes: int


def _walk(devices: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for device in devices:
        yield device
        yield from _walk(device.get("children") or [])


def _subtree(device: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_walk([device]))


def _mountpoints(device: dict[str, Any]) -> set[str]:
    return {
        mountpoint
        for item in _subtree(device)
        for mountpoint in item.get("mountpoints", [])
        if mountpoint
    }


def _size(device: dict[str, Any]) -> int:
    value = device.get("size_bytes")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SelectionError(f"Invalid or unknown capacity for {device.get('path')}")
    return value


def validate_clone_selection(
    inventory: dict[str, Any],
    source_path: str,
    target_path: str,
    protected_disk_paths: set[str] | None = None,
) -> CloneSelection:
    """Validate a whole-disk clone pair against a previously collected inventory.

    Both selections must identify unique top-level disks. Mounted source or target
    trees are rejected, and a disk containing the live root filesystem cannot be
    selected. The target must be at least as large as the source.
    """
    if not source_path or not target_path:
        raise SelectionError("Both source and target disk paths are required")
    if source_path == target_path:
        raise SelectionError("Source and target must be different disks")

    devices = inventory.get("devices")
    if not isinstance(devices, list):
        raise SelectionError("Inventory has no valid devices list")

    matches = [
        device for device in _walk(devices)
        if device.get("path") in (source_path, target_path)
    ]
    for path in (source_path, target_path):
        path_matches = [device for device in matches if device.get("path") == path]
        if len(path_matches) != 1:
            raise SelectionError(f"Disk path is missing or ambiguous: {path}")
        if path_matches[0].get("type") != "disk" or path_matches[0] not in devices:
            raise SelectionError(f"Whole-disk selection required: {path}")

    source = next(device for device in devices if device.get("path") == source_path)
    target = next(device for device in devices if device.get("path") == target_path)

    if protected_disk_paths is None:
        raise SelectionError("Live root protection data is required")
    protected = protected_disk_paths
    if source_path in protected or target_path in protected:
        raise SelectionError("A selected disk backs the live system root")

    if target.get("read_only"):
        raise SelectionError(f"Target disk is read-only: {target_path}")

    root_disks = [
        device.get("path")
        for device in devices
        if "/" in _mountpoints(device)
    ]
    if source_path in root_disks or target_path in root_disks:
        raise SelectionError("The live system root disk cannot be selected")

    source_mounts = _mountpoints(source)
    target_mounts = _mountpoints(target)
    if source_mounts:
        raise SelectionError(
            f"Source disk has mounted filesystems: {', '.join(sorted(source_mounts))}"
        )
    if target_mounts:
        raise SelectionError(
            f"Target disk has mounted filesystems: {', '.join(sorted(target_mounts))}"
        )

    source_size = _size(source)
    target_size = _size(target)
    if target_size < source_size:
        raise SelectionError(
            f"Target is too small ({target_size} bytes); "
            f"source requires {source_size} bytes"
        )

    return CloneSelection(
        source_path=source_path,
        target_path=target_path,
        source_size_bytes=source_size,
        target_size_bytes=target_size,
    )
