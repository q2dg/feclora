"""Local rescue UI for inspection, capture and verified image restoration."""
from __future__ import annotations
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from feclora.storage.disk_capture import DiskCaptureError, capture_disk
from feclora.storage.disk_clone import DiskCloneCancelled, DiskCloneError, clone_disk
from feclora.storage.disk_restore import DiskRestoreError, restore_disk
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import InventoryError, collect_inventory
from feclora.storage.partition_image_capture import PartitionImageCaptureError, capture_partition_image
from feclora.storage.partition_restore import PartitionRestoreError, restore_partition

IMAGE_REPOSITORY = "/home/feclora/images"

def device_details(device: dict[str, Any]) -> str:
    lines = [
        f"Device: {device.get('path') or device.get('name') or 'unknown'}",
        f"Type: {device.get('type') or 'unknown'}",
        f"Size: {device.get('size_bytes') if device.get('size_bytes') is not None else 'unknown'} bytes",
        f"Read-only flag: {'yes' if device.get('read_only') else 'no'}",
        f"Model: {device.get('model') or 'unknown'}",
        f"Vendor: {device.get('vendor') or 'unknown'}",
        f"Transport: {device.get('transport') or 'unknown'}",
        f"Serial: {device.get('serial') or 'unknown'}",
        f"Filesystem: {device.get('filesystem') or 'none detected'}",
        f"Mountpoints: {', '.join(device.get('mountpoints') or []) or 'none'}",
        "", "Child devices / partitions:",
    ]
    def append_children(children: list[dict[str, Any]], depth: int = 0) -> None:
        for child in children:
            path = child.get("path") or child.get("name") or "unknown"
            size = child.get("size_bytes")
            fs = child.get("filesystem") or "no filesystem detected"
            lines.append("  " * depth + f"- {path} | {size if size is not None else '?'} bytes | {fs}")
            append_children(child.get("children") or [], depth + 1)
    append_children(device.get("children") or [])
    return "\n".join(lines)

def _dialog(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["dialog", "--stdout", *args], check=False, capture_output=True, text=True)

def _message(title: str, message: str) -> None:
    _dialog(["--title", title, "--msgbox", message, "18", "82"])

def _input(title: str, prompt: str, initial: str = "") -> str | None:
    result = _dialog(["--title", title, "--inputbox", prompt, "12", "78", initial])
    return result.stdout.strip() if result.returncode == 0 else None

def _menu(title: str, prompt: str, choices: list[tuple[str, str]]) -> str | None:
    if not choices:
        _message(title, "No applicable choices were found.")
        return None
    args = ["--title", title, "--menu", prompt, "20", "90", "12"]
    for value, label in choices:
        args.extend([value, label])
    result = _dialog(args)
    return result.stdout.strip() if result.returncode == 0 else None

def _walk(devices: list[dict[str, Any]]):
    for item in devices:
        yield item
        yield from _walk(item.get("children") or [])

def _select_devices(inventory: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    devices = inventory["devices"]
    if kind == "disk":
        return [item for item in devices if item.get("type") == "disk"]
    return [item for item in _walk(devices) if item.get("type") == "part"]

def _select_device(inventory: dict[str, Any], kind: str, title: str, prompt: str):
    items = _select_devices(inventory, kind)
    choices = []
    for item in items:
        path = item.get("path")
        if path:
            size = item.get("size_bytes")
            label = f"{path} | {size if size is not None else '?'} bytes | {item.get('filesystem') or 'unknown FS'}"
            choices.append((path, label))
    selected = _menu(title, prompt, choices)
    return next((item for item in items if item.get("path") == selected), None)

def _compression() -> str | None:
    return _menu("Image compression", "Choose storage compression.", [
        ("none", "None (fastest, largest)"),
        ("gzip", "gzip"),
        ("xz", "xz (slower, smaller)"),
    ])

def _repository() -> str:
    os.makedirs(IMAGE_REPOSITORY, mode=0o700, exist_ok=True)
    info = os.lstat(IMAGE_REPOSITORY)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("image repository must be a real directory, not a symlink")
    os.chmod(IMAGE_REPOSITORY, 0o700)
    return IMAGE_REPOSITORY

def _capture_disk(inventory: dict[str, Any]) -> None:
    source = _select_device(inventory, "disk", "Capture whole disk", "Select the source disk. This operation reads it only.")
    if source is None:
        return
    image_id = _input("Capture whole disk", "Image identifier (letters, digits, . _ -):")
    if not image_id:
        return
    compression = _compression()
    if compression is None:
        return
    try:
        manifest = capture_disk(source["path"], image_id, _repository(), compression=compression)
        _message("Capture completed", f"Image {manifest.image_id} captured.\nManifest: {manifest.image_id}.manifest.json")
    except (DiskCaptureError, OSError) as exc:
        _message("Capture failed", str(exc))

def _capture_partition(inventory: dict[str, Any]) -> None:
    source = _select_device(inventory, "part", "Capture partition", "Select the source partition. This operation reads it only.")
    if source is None:
        return
    image_id = _input("Capture partition", "Image identifier (letters, digits, . _ -):")
    if not image_id:
        return
    compression = _compression()
    if compression is None:
        return
    partition_id = os.path.basename(source["path"])
    try:
        manifest = capture_partition_image(
            source["path"], image_id, partition_id, _repository(), compression=compression,
        )
        _message("Capture completed", f"Partition image {manifest.image_id} captured.\nManifest: {manifest.image_id}.manifest.json")
    except (PartitionImageCaptureError, OSError) as exc:
        _message("Capture failed", str(exc))

def _clone_disk(inventory: dict[str, Any]) -> None:
    source = _select_device(
        inventory, "disk", "Clone whole disk - source",
        "Select the source disk. It must be offline and not mounted.",
    )
    if source is None:
        return
    targets = [
        item for item in _select_devices(inventory, "disk")
        if item.get("path") and item.get("path") != source.get("path")
    ]
    choices = []
    for item in targets:
        path = item["path"]
        size = item.get("size_bytes")
        choices.append((path, f"{path} | {size if size is not None else '?'} bytes"))
    target_path = _menu(
        "Clone whole disk - destination",
        "Select the destination. ALL DATA ON IT WILL BE OVERWRITTEN.",
        choices,
    )
    if target_path is None:
        return
    phrase = f"ERASE {target_path}"
    typed = _input("Destructive confirmation", f"Source: {source['path']}\\nDestination: {target_path}\\nType exactly:\\n{phrase}")
    if typed != phrase:
        _message("Clone cancelled", "The confirmation did not match. No write was started.")
        return
    gauge = None
    try:
        gauge = subprocess.Popen(
            ["dialog", "--title", "Cloning disk", "--gauge",
             f"Copying {source['path']} to {target_path}. Press Esc to cancel.",
             "10", "76", "0"],
            stdin=subprocess.PIPE, text=True,
        )
        def report_progress(percent: int, _detail: str) -> None:
            if gauge is None or gauge.poll() is not None or gauge.stdin is None:
                raise BrokenPipeError("progress dialog was closed")
            gauge.stdin.write(f"{percent}\n")
            gauge.stdin.flush()
        copied = clone_disk(
            source["path"], target_path, confirmation=typed,
            progress_callback=report_progress,
        )
        if gauge is not None and gauge.stdin is not None:
            gauge.stdin.write("100\n")
            gauge.stdin.close()
            gauge.stdin = None
            gauge.wait()
        _message(
            "Clone completed",
            f"Copied {copied} bytes from {source['path']} to {target_path}.\\n"
            f"Copied {copied} bytes from {source['path']} to {target_path}.\n"
        )
    except DiskCloneCancelled as exc:
        _message("Clone cancelled", str(exc) + "\nThe destination may contain a partial clone.")
    except (DiskCloneError, OSError) as exc:
        _message("Clone failed", str(exc))
    finally:
        if gauge is not None:
            if gauge.stdin is not None:
                gauge.stdin.close()
            if gauge.poll() is None:
                gauge.terminate()
                gauge.wait()


def _available_manifests() -> list[tuple[str, ImageManifest]]:
    repository = _repository()
    found = []
    for path in sorted(Path(repository).glob("*.manifest.json")):
        try:
            manifest = ImageManifest.from_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ManifestValidationError):
            continue
        found.append((path.name, manifest))
    return found

def _restore(inventory: dict[str, Any]) -> None:
    try:
        manifests = _available_manifests()
    except OSError as exc:
        _message("Image repository error", str(exc))
        return
    choices = [
        (filename, f"{manifest.image_id} | {manifest.image_type} | {manifest.source_size_bytes} bytes")
        for filename, manifest in manifests
    ]
    filename = _menu("Restore image", "Select a verified image manifest.", choices)
    if filename is None:
        return
    manifest = next(item for name, item in manifests if name == filename)
    kind = "disk" if manifest.image_type == "disk" else "part"
    target = _select_device(
        inventory, kind, "Restore target",
        "Select the destination. ALL DATA ON IT WILL BE OVERWRITTEN.",
    )
    if target is None:
        return
    phrase = f"ERASE {target['path']}"
    typed = _input("Destructive confirmation", f"Type exactly:\n{phrase}")
    if typed != phrase:
        _message("Restore cancelled", "The confirmation did not match. No write was started.")
        return
    try:
        if manifest.image_type == "disk":
            restore_disk(filename, _repository(), target["path"], confirmation=typed)
        else:
            restore_partition(filename, _repository(), target["path"], confirmation=typed)
        _message("Restore completed", f"Restore utility completed successfully for {target['path']}.\nVerify the resulting system before relying on it.")
    except (DiskRestoreError, PartitionRestoreError, OSError) as exc:
        _message("Restore failed", str(exc))

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
        choice = _menu("feclora - Local rescue", "Inspect, capture or restore storage. Restore operations overwrite their target.", [
            ("inspect", "Inspect disks and partitions"),
            ("capture-disk", "Capture a whole disk"),
            ("capture-partition", "Capture a partition"),
            ("restore", "Restore an image"),
            ("clone-disk", "Clone one local disk directly to another"),
            ("exit", "Return to operating mode selector"),
        ])
        if choice in (None, "exit"):
            return 0
        if choice == "inspect":
            selected = _select_device(inventory, "disk", "Storage inventory", "Select a disk to inspect.")
            if selected:
                _message("Device details - read only", device_details(selected))
        elif choice == "capture-disk":
            _capture_disk(inventory)
        elif choice == "capture-partition":
            _capture_partition(inventory)
        elif choice == "restore":
            _restore(inventory)
        elif choice == "clone-disk":
            _clone_disk(inventory)

if __name__ == "__main__":
    raise SystemExit(main())
