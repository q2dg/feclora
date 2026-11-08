"""Read-only block-device inventory based on util-linux lsblk."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Callable

from feclora.storage.volume_metadata import annotate_inventory
from feclora.storage.volume_topology import collect_lvm_topology
from feclora.storage.btrfs_inventory import collect_btrfs_topology

LSBLK_COLUMNS = (
    "NAME,PATH,TYPE,SIZE,RO,TRAN,MODEL,VENDOR,SERIAL,WWN,"
    "FSTYPE,LABEL,UUID,MOUNTPOINTS"
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
    inventory = annotate_inventory({"schema_version": 1, "devices": devices})\n    inventory["volume_topology"] = collect_lvm_topology(which=shutil.which, runner=runner)\n    inventory["btrfs_topology"] = collect_btrfs_topology(which=shutil.which, runner=runner)\n    return inventory


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
    return parse_lsblk(result.stdout)


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
