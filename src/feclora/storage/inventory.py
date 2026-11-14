"""Read-only block-device inventory based on util-linux lsblk."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Callable

from feclora.storage.volume_metadata import annotate_inventory
from feclora.storage.volume_topology import collect_lvm_topology, VolumeTopologyError
from feclora.storage.btrfs_inventory import collect_btrfs_topology, collect_btrfs_subvolumes, BtrfsInventoryError
from feclora.storage.stratis_inventory import collect_stratis_topology, StratisInventoryError
from feclora.storage.luks_inventory import collect_luks_inventory, LuksInventoryError
from feclora.storage.topology_graph import build_storage_graph

LSBLK_COLUMNS = (
    "NAME,PATH,TYPE,SIZE,RO,TRAN,MODEL,VENDOR,SERIAL,WWN,"
    "FSTYPE,LABEL,UUID,PARTUUID,PARTTYPE,PARTLABEL,MAJ:MIN,LOG-SEC,MOUNTPOINTS"
)


class InventoryError(RuntimeError):
    """Raised when the block-device inventory cannot be collected."""


def _clean_mountpoints(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _normalize_device(device: dict[str, Any]) -> dict[str, Any]:
    """Return a stable schema while tolerating absent lsblk columns."""
    normalized = {
        "name": device.get("name"),
        "path": device.get("path") or device.get("name"),
        "type": device.get("type"),
        "size_bytes": device.get("size"),
        "read_only": bool(device.get("ro", False)),
        "transport": device.get("tran"),
        "model": device.get("model"),
        "vendor": device.get("vendor"),
        "serial": device.get("serial"),
        "wwn": device.get("wwn"),
        "filesystem": device.get("fstype"),
        "label": device.get("label"),
        "uuid": device.get("uuid"),
        "partuuid": device.get("partuuid"),
        "partition_type_guid": device.get("parttype"),
        "partition_label": device.get("partlabel"),
        "major_minor": device.get("maj:min"),
        "logical_sector_size": device.get("log-sec"),
        "mountpoints": _clean_mountpoints(
            device.get("mountpoints", device.get("mountpoint"))
        ),
        "children": [],
    }
    children = device.get("children") or []
    normalized["children"] = [
        _normalize_device(child) for child in children if isinstance(child, dict)
    ]
    return normalized


def parse_lsblk(payload: str) -> dict[str, Any]:
    """Parse lsblk JSON and return a version-stable inventory document."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"lsblk returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("blockdevices"), list):
        raise InventoryError("lsblk JSON does not contain a blockdevices list")

    devices = [
        _normalize_device(item)
        for item in data["blockdevices"]
        if isinstance(item, dict)
    ]
    return annotate_inventory({"schema_version": 1, "devices": devices})


def collect_inventory(
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Collect block-device metadata. The command only queries kernel metadata."""
    if runner is None:
        runner = subprocess.run
    executable = shutil.which("lsblk")
    if executable is None:
        raise InventoryError("lsblk was not found; install util-linux")

    command = [
        executable,
        "--json",
        "--bytes",
        "--paths",
        "--output",
        LSBLK_COLUMNS,
    ]
    try:
        result = runner(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise InventoryError("lsblk timed out while reading device metadata") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise InventoryError(f"lsblk failed: {detail or exc}") from exc
    inventory = parse_lsblk(result.stdout)
    try:
        inventory["volume_topology"] = collect_lvm_topology(which=shutil.which, runner=runner)
    except VolumeTopologyError as exc:
        inventory["volume_topology"] = {"status": "error", "error": str(exc)}
    try:
        inventory["btrfs_topology"] = collect_btrfs_topology(which=shutil.which, runner=runner)
    except BtrfsInventoryError as exc:
        inventory["btrfs_topology"] = {"status": "error", "error": str(exc)}
    try:
        inventory["btrfs_subvolumes"] = collect_btrfs_subvolumes(which=shutil.which, runner=runner)
    except BtrfsInventoryError as exc:
        inventory["btrfs_subvolumes"] = {"status": "error", "error": str(exc)}
    try:
        inventory["stratis_topology"] = collect_stratis_topology()
    except StratisInventoryError as exc:
        inventory["stratis_topology"] = {"status": "error", "error": str(exc)}
    try:
        inventory["luks_metadata"] = collect_luks_inventory(inventory["devices"], which=shutil.which, runner=runner)
    except LuksInventoryError as exc:
        inventory["luks_metadata"] = {"status": "error", "error": str(exc), "containers": []}
    inventory["storage_graph"] = build_storage_graph(inventory)
    return inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List block devices and filesystems without modifying them."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="write the inventory as JSON (default output)",
    )
    args = parser.parse_args(argv)
    del args  # JSON is the sole output format in this initial implementation.

    try:
        inventory = collect_inventory()
    except InventoryError as exc:
        print(f"feclora-inventory: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(inventory, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def assess_disk_compatibility(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Compare two inventoried whole disks without probing or modifying either."""
    blockers: list[str] = []
    warnings: list[str] = []
    if source.get("type") != "disk" or target.get("type") != "disk":
        blockers.append("Both source and destination must be whole disks.")
    source_path, target_path = source.get("path"), target.get("path")
    if not source_path or not target_path:
        blockers.append("A source or destination device path is unknown.")
    elif source_path == target_path:
        blockers.append("Source and destination refer to the same device path.")
    if target.get("read_only"):
        blockers.append("Destination is marked read-only.")
    if target.get("mountpoints"):
        blockers.append("Destination has mounted filesystems: " + ", ".join(target["mountpoints"]))
    if source.get("mountpoints"):
        warnings.append("Source has mounted filesystems: " + ", ".join(source["mountpoints"]) + ".")
    source_size, target_size = source.get("size_bytes"), target.get("size_bytes")
    if not isinstance(source_size, int) or source_size <= 0:
        warnings.append("Source capacity is unknown; capacity compatibility cannot be established.")
    elif not isinstance(target_size, int) or target_size <= 0:
        blockers.append("Destination capacity is unknown; refusing an unverified size comparison.")
    elif target_size < source_size:
        blockers.append(f"Destination is smaller than source ({target_size} < {source_size} bytes).")
    elif target_size > source_size:
        warnings.append("Destination is larger; partition layout will be copied as-is (no proportional growth).")
    source_sector, target_sector = source.get("logical_sector_size"), target.get("logical_sector_size")
    if source_sector not in {512, 4096} or target_sector not in {512, 4096}:
        warnings.append("Logical sector size is unknown or unsupported; engine preflight must decide.")
    elif source_sector != target_sector:
        blockers.append(f"Logical sector sizes differ ({source_sector} vs {target_sector} bytes).")
    source_transport, target_transport = source.get("transport"), target.get("transport")
    if source_transport and target_transport and source_transport != target_transport:
        warnings.append(f"Transport differs ({source_transport} to {target_transport}); verify target firmware/driver support.")
    if not source.get("model") or not target.get("model"):
        warnings.append("Model metadata is incomplete; physical device identity should be checked manually.")
    return {"compatible": not blockers, "blockers": blockers, "warnings": warnings}
