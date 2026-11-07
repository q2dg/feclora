"""Minimal read-only storage browser using the standard dialog utility."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

from feclora.storage.inventory import InventoryError, collect_inventory


def device_details(device: dict[str, Any]) -> str:
    """Format one device and its descendants for a read-only detail screen."""
    lines = [
        f"Device: {device.get('path') or device.get('name') or 'unknown'}",
        f"Type: {device.get('type') or 'unknown'}",
        f"Size: {device.get('size_bytes') if device.get('size_bytes') is not None else 'unknown'} bytes",
        f"Read-only flag: {'yes' if device.get('read_only') else 'no'}",
        f"Model: {device.get('model') or 'unknown'}",
        f"Vendor: {device.get('vendor') or 'unknown'}",
        f"Transport: {device.get('transport') or 'unknown'}",
        f"Serial: {device.get('serial') or 'unknown'}",
        f"WWN: {device.get('wwn') or 'unknown'}",
        f"Filesystem: {device.get('filesystem') or 'none detected'}",
        f"Label: {device.get('label') or 'none'}",
        f"UUID: {device.get('uuid') or 'none'}",
        f"Mountpoints: {', '.join(device.get('mountpoints') or []) or 'none'}",
        "",
        "Child devices / partitions:",
    ]

    def append_children(children: list[dict[str, Any]], depth: int = 0) -> None:
        for child in children:
            prefix = "  " * depth
            path = child.get("path") or child.get("name") or "unknown"
            size = child.get("size_bytes")
            filesystem = child.get("filesystem") or "no filesystem detected"
            lines.append(f"{prefix}- {path} | {size if size is not None else '?'} bytes | {filesystem}")
            append_children(child.get("children") or [], depth + 1)

    append_children(device.get("children") or [])
    return "\n".join(lines)


def _dialog(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dialog", "--stdout", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _message(title: str, message: str) -> None:
    _dialog(["--title", title, "--msgbox", message, "20", "76"])


def main() -> int:
    if shutil.which("dialog") is None:
        print("feclora-ui: install the 'dialog' package to use this interface", file=sys.stderr)
        return 1

    while True:
        try:
            inventory = collect_inventory()
        except InventoryError as exc:
            _message("Storage inventory error", str(exc))
            return 1

        devices = inventory["devices"]
        if not devices:
            _message("Storage inventory", "No block devices were reported by lsblk.")
            return 0

        menu = [
            "exit", "Exit",
        ]
        for device in devices:
            path = device.get("path") or device.get("name") or "unknown"
            size = device.get("size_bytes")
            kind = device.get("type") or "device"
            label = f"{path} | {kind} | {size if size is not None else '?'} bytes"
            menu.extend([path, label])

        result = _dialog([
            "--title", "feclora - Storage inventory",
            "--menu",
            "Select a device to inspect. This screen does not modify storage.",
            "20", "90", "12",
            *menu,
        ])

        if result.returncode != 0 or result.stdout.strip() == "exit":
            return 0

        selected = result.stdout.strip()
        device = next(
            (item for item in devices if (item.get("path") or item.get("name")) == selected),
            None,
        )
        if device is not None:
            _message("Device details - read only", device_details(device))


if __name__ == "__main__":
    raise SystemExit(main())
