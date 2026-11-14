"""Local rescue UI for inspection, capture and verified image restoration."""
from __future__ import annotations
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from feclora.storage.capture import CaptureCancelled
from feclora.storage.disk_capture import DiskCaptureError, capture_disk
from feclora.storage.disk_clone import DiskCloneCancelled, DiskCloneError, clone_disk
from feclora.storage.disk_image_partition import DiskImagePartitionError, extract_partition_image
from feclora.storage.disk_restore import DiskRestoreCancelled, DiskRestoreError, restore_disk
from feclora.storage.proportional_staging import ProportionalStagingError, stage_verified_raw_disk_image
from feclora.storage.proportional_restore import StagedProportionalRestoreError, restore_staged_proportional_image
from feclora.storage.proportional_restore_workflow import ProportionalRestoreWorkflowError, prepare_from_offline_source_disk
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import InventoryError, collect_inventory, assess_disk_compatibility
from feclora.storage.partition_image_capture import PartitionImageCaptureError, capture_partition_image
from feclora.storage.partition_clone import PartitionCloneCancelled, PartitionCloneError, clone_partition
from feclora.storage.partition_restore import PartitionRestoreCancelled, PartitionRestoreError, restore_partition
from feclora.storage.operation_log import DEFAULT_LOG_PATH, OperationLogError, operation_record
from feclora.storage.restore_profile import RestoreProfile, RestoreProfileError, RestoreTargetSelector, save_unattended_restore_profile

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
        f"Volume layers: {', '.join(device.get('volume_features') or []) or 'none detected'}",
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

def volume_topology_details(inventory: dict[str, Any]) -> str:
    """Format read-only LVM, LUKS, Stratis and Btrfs topology for the rescue UI."""
    lines: list[str] = []
    lvm = inventory.get("volume_topology") or {}
    lines.append("LVM topology: " + str(lvm.get("status", "not collected")))
    for section, keys in (
        ("pvs", ("pv_name", "vg_name", "pv_size", "pv_free", "pv_uuid")),
        ("vgs", ("vg_name", "vg_size", "vg_free", "pv_count", "lv_count")),
        ("lvs", ("lv_path", "vg_name", "lv_size", "origin", "pool_lv", "devices")),
    ):
        for row in lvm.get(section, []):
            fields = [f"{key}={row.get(key)}" for key in keys if row.get(key) not in (None, "")]
            lines.append("  " + section[:-1].upper() + ": " + " | ".join(fields))
    if lvm.get("error"):
        lines.append("  Error: " + str(lvm["error"]))
    luks = inventory.get("luks_metadata") or {}
    lines.append("LUKS header metadata: " + str(luks.get("status", "not collected")))
    for container in luks.get("containers", []):
        lines.append("  Container: " + str(container.get("device")) + " | LUKS" + str(container.get("version")) + " | UUID " + str(container.get("uuid")) + " | cipher " + str(container.get("cipher") or "unknown") + " | enabled keyslots " + str(container.get("keyslot_count", "unknown")) + " | tokens " + str(container.get("token_count", "unknown")))
    if luks.get("error"):
        lines.append("  Error: " + str(luks["error"]))
    stratis = inventory.get("stratis_topology") or {}
    lines.append("Stratis topology: " + str(stratis.get("status", "not collected")))
    for pool in stratis.get("pools", []):
        lines.append("  Pool: " + str(pool.get("name")))
        for filesystem in pool.get("filesystems", []):
            lines.append("    Filesystem: " + str(filesystem.get("name")) + " -> " + str(filesystem.get("mapper_device")))
            lines.append("      Backing devices: " + ", ".join(filesystem.get("backing_block_devices", [])))
    if stratis.get("error"):
        lines.append("  Error: " + str(stratis["error"]))
    btrfs = inventory.get("btrfs_topology") or {}
    lines.append("Btrfs topology: " + str(btrfs.get("status", "not collected")))
    for filesystem in btrfs.get("filesystems", []):
        lines.append("  Filesystem: " + str(filesystem.get("label") or "(no label)") + " | UUID " + str(filesystem.get("uuid")))
        for device in filesystem.get("devices", []):
            lines.append("    Device " + str(device.get("devid")) + ": " + str(device.get("path")) + " | " + str(device.get("size_bytes")) + " bytes")
    if btrfs.get("error"):
        lines.append("  Error: " + str(btrfs["error"]))
    subvolumes = inventory.get("btrfs_subvolumes") or {}
    lines.append("Btrfs subvolumes: " + str(subvolumes.get("status", "not collected")))
    for mount in subvolumes.get("mounts", []):
        lines.append("  Mounted at: " + str(mount.get("mountpoint")))
        for subvolume in mount.get("subvolumes", []):
            lines.append("    " + str(subvolume.get("kind")) + ": " + str(subvolume.get("path")) + " | UUID " + str(subvolume.get("uuid")))
    if subvolumes.get("error"):
        lines.append("  Error: " + str(subvolumes["error"]))
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

def _compression() -> tuple[str, int | None] | None:
    tool = _menu("Image compression", "Choose compression tool. No compression is also available.", [
        ("none", "None (fastest, largest)"),
        ("gzip", "gzip"),
        ("xz", "xz"),
        ("zstd", "zstd"),
        ("lz4", "lz4"),
    ])
    if tool is None:
        return None
    if tool == "none":
        return ("none", None)
    levels = [("1", "1 - fastest"), ("3", "3 - fast"), ("6", "6 - balanced"), ("9", "9 - maximum")]
    if tool == "xz":
        levels = [("0", "0 - fastest"), ("3", "3 - fast"), ("6", "6 - balanced"), ("9", "9 - maximum")]
    elif tool == "zstd":
        levels = [("1", "1 - fastest"), ("3", "3 - default"), ("6", "6 - balanced"), ("9", "9 - high ratio"), ("15", "15 - very high ratio"), ("19", "19 - maximum standard")]
    elif tool == "lz4":
        levels = [("1", "1 - fastest"), ("3", "3 - fast"), ("6", "6 - balanced"), ("9", "9 - high ratio"), ("12", "12 - maximum")]
    selected = _menu(f"{tool} compression level", "Higher levels use more CPU and usually produce smaller images.", levels)
    return (tool, int(selected)) if selected is not None else None


def _image_security_options() -> str | None | bool:
    """Choose optional age encryption; SHA-256 integrity checks are unconditional."""
    choices = [("none", "No encryption")]
    if shutil.which("age"):
        choices.append(("age", "Encrypt with age"))
    mode = _menu(
        "Image encryption",
        "Choose optional confidentiality protection. SHA-256 integrity verification is always applied.",
        choices,
    )
    if mode is None:
        return False
    if mode == "none":
        return None
    default_recipients = (
        "/etc/feclora/pki/age-recipients.txt"
        if os.path.isfile("/etc/feclora/pki/age-recipients.txt") else ""
    )
    recipients = _input(
        "age recipients", "Path to recipients file (public age keys, one per line):",
        initial=default_recipients,
    )
    return recipients or False

def _repository() -> str:
    os.makedirs(IMAGE_REPOSITORY, mode=0o700, exist_ok=True)
    info = os.lstat(IMAGE_REPOSITORY)
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("image repository must be a real directory, not a symlink")
    os.chmod(IMAGE_REPOSITORY, 0o700)
    return IMAGE_REPOSITORY

def _run_logged(operation: str, target: str, image_id: str | None, callback: Callable[[], Any]) -> Any:
    with operation_record(operation, target, image_id=image_id):
        return callback()


def _run_capture_gauge(
    title: str,
    description: str,
    operation: Callable[[Callable[[int, int | None], None]], Any],
) -> Any:
    gauge = subprocess.Popen(
        ["dialog", "--title", title, "--gauge", description, "10", "76", "0"],
        stdin=subprocess.PIPE, text=True,
    )
    def report_progress(done: int, total: int | None) -> None:
        if gauge.poll() is not None or gauge.stdin is None:
            raise CaptureCancelled("progress dialog closed; capture was cancelled")
        percent = min(99, int(done * 100 / total)) if total else 0
        gauge.stdin.write(f"XXX\n{percent}\nRead {done:,} bytes\nXXX\n")
        gauge.stdin.flush()
    try:
        result = operation(report_progress)
        if gauge.stdin is not None:
            try:
                gauge.stdin.write("100\n")
                gauge.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                gauge.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            gauge.stdin = None
        gauge.wait()
        return result
    except (BrokenPipeError, OSError) as exc:
        raise CaptureCancelled(f"capture cancelled because progress dialog closed: {exc}") from exc
    finally:
        if gauge.stdin is not None:
            try:
                gauge.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if gauge.poll() is None:
            gauge.terminate()
            gauge.wait()


def _capture_disk(inventory: dict[str, Any]) -> None:
    source = _select_device(inventory, "disk", "Capture whole disk", "Select the source disk. This operation reads it only.")
    if source is None:
        return
    image_id = _input("Capture whole disk", "Image identifier (letters, digits, . _ -):")
    if not image_id:
        return
    compression_choice = _compression()
    if compression_choice is None:
        return
    compression, compression_level = compression_choice
    security = _image_security_options()
    if security is False:
        return
    recipients = security
    try:
        manifest = _run_logged("capture_disk", source["path"], image_id, lambda: _run_capture_gauge(
            "Capturing whole disk", f"Reading {source['path']} into image repository.",
            lambda progress: capture_disk(
                source["path"], image_id, _repository(), compression=compression,
                compression_level=compression_level, age_recipients_file=recipients,
                progress_callback=progress,
            ),
        ))
        _message("Capture completed", f"Image {manifest.image_id} captured.\nManifest: {manifest.image_id}.manifest.json")
    except CaptureCancelled as exc:
        _message("Capture cancelled", str(exc) + "\nNo manifest was published.")
    except (DiskCaptureError, OperationLogError, OSError) as exc:
        _message("Capture failed", str(exc))

def _capture_partition(inventory: dict[str, Any]) -> None:
    source = _select_device(inventory, "part", "Capture partition", "Select the source partition. This operation reads it only.")
    if source is None:
        return
    image_id = _input("Capture partition", "Image identifier (letters, digits, . _ -):")
    if not image_id:
        return
    compression_choice = _compression()
    if compression_choice is None:
        return
    compression, compression_level = compression_choice
    security = _image_security_options()
    if security is None:
        return
    recipients, signing_key = security
    partition_id = os.path.basename(source["path"])
    try:
        manifest = _run_logged("capture_partition", source["path"], image_id, lambda: _run_capture_gauge(
            "Capturing partition", f"Reading {source['path']} into image repository.",
            lambda progress: capture_partition_image(
                source["path"], image_id, partition_id, _repository(),
                compression=compression, compression_level=compression_level,
                age_recipients_file=recipients,
                progress_callback=progress, inventory=inventory,
            ),
        ))
        _message("Capture completed", f"Partition image {manifest.image_id} captured.\nManifest: {manifest.image_id}.manifest.json")
    except CaptureCancelled as exc:
        _message("Capture cancelled", str(exc) + "\nNo manifest was published.")
    except (PartitionImageCaptureError, OperationLogError, OSError) as exc:
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
    compatibility = assess_disk_compatibility(source, next(item for item in targets if item.get("path") == target_path))
    report = ["Preflight compatibility: " + ("NO BLOCKERS FOUND" if compatibility["compatible"] else "BLOCKED")]
    report.extend("BLOCKER: " + item for item in compatibility["blockers"])
    report.extend("WARNING: " + item for item in compatibility["warnings"])
    report.append("This report is advisory; the cloning engine repeats its own safety and geometry checks.")
    _message("Disk compatibility preflight", "\n".join(report))
    if not compatibility["compatible"]:
        return
    phrase = f"ERASE {target_path}"
    typed = _input("Destructive confirmation", f"Source: {source['path']}\nDestination: {target_path}\nType exactly:\n{phrase}")
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
        copied = _run_logged("clone_disk", target_path, None, lambda: clone_disk(
            source["path"], target_path, confirmation=typed,
            progress_callback=report_progress,
        ))
        if gauge is not None and gauge.stdin is not None:
            try:
                gauge.stdin.write("100\n")
                gauge.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                gauge.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            gauge.stdin = None
            gauge.wait()
        _message(
            "Clone completed",
            f"Copied {copied} bytes from {source['path']} to {target_path}.\n"
            "The destination was flushed by dd. Read-back verification is not yet implemented."
        )
    except DiskCloneCancelled as exc:
        _message("Clone cancelled", str(exc) + "\nThe destination may contain a partial clone.")
    except (DiskCloneError, OperationLogError, OSError) as exc:
        _message("Clone failed", str(exc))
    finally:
        if gauge is not None:
            if gauge.stdin is not None:
                try:
                    gauge.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if gauge.poll() is None:
                gauge.terminate()
                gauge.wait()


def _clone_partition(inventory: dict[str, Any]) -> None:
    source = _select_device(
        inventory, "part", "Clone partition - source",
        "Select the source partition. It must be offline and not mounted.",
    )
    if source is None:
        return
    targets = [
        item for item in _select_devices(inventory, "part")
        if item.get("path") and item.get("path") != source.get("path")
    ]
    choices = [
        (item["path"], f"{item['path']} | {item.get('size_bytes') or '?'} bytes")
        for item in targets
    ]
    target_path = _menu(
        "Clone partition - destination",
        "Select the destination partition. Its contents will be overwritten.",
        choices,
    )
    if target_path is None:
        return
    phrase = f"ERASE {target_path} FROM {source['path']}"
    typed = _input(
        "Destructive confirmation",
        f"Source: {source['path']}\nDestination: {target_path}\nType exactly:\n{phrase}",
    )
    if typed != phrase:
        _message("Clone cancelled", "The confirmation did not match. No write was started.")
        return

    gauge = None
    try:
        gauge = subprocess.Popen(
            ["dialog", "--title", "Cloning partition", "--gauge",
             f"Copying {source['path']} to {target_path}; destination read-back will be verified.",
             "10", "76", "0"],
            stdin=subprocess.PIPE, text=True,
        )
        def report_progress(done: int, total: int) -> None:
            if gauge is None or gauge.poll() is not None or gauge.stdin is None:
                raise PartitionCloneCancelled("progress dialog closed; partition clone was cancelled")
            percent = min(99, int(done * 100 / total)) if total else 0
            gauge.stdin.write(f"{percent}\n")
            gauge.stdin.flush()
        copied = _run_logged(
            "clone_partition", target_path, None,
            lambda: clone_partition(
                source["path"], target_path, confirmation=typed,
                progress_callback=report_progress,
            ),
        )
        if gauge is not None and gauge.stdin is not None:
            gauge.stdin.write("100\n")
            gauge.stdin.flush()
            gauge.stdin.close()
            gauge.stdin = None
            gauge.wait()
        _message(
            "Partition clone completed",
            f"Copied and read-back verified {copied:,} bytes from {source['path']} to {target_path}.",
        )
    except PartitionCloneCancelled as exc:
        _message("Partition clone cancelled", str(exc) + "\nThe destination may contain a partial clone.")
    except (PartitionCloneError, OperationLogError, OSError) as exc:
        _message("Partition clone failed", str(exc))
    finally:
        if gauge is not None:
            if gauge.stdin is not None:
                try:
                    gauge.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if gauge.poll() is None:
                gauge.terminate()
                gauge.wait()


def _show_operation_log() -> None:
    try:
        fd = os.open(DEFAULT_LOG_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OperationLogError("operation log is not a regular file")
            os.lseek(fd, max(0, info.st_size - 65536), os.SEEK_SET)
            raw = os.read(fd, 65536)
        finally:
            os.close(fd)
    except FileNotFoundError:
        _message("Operation history", "No operations have been recorded yet.")
        return
    except (OSError, OperationLogError) as exc:
        _message("Operation history error", str(exc))
        return
    events = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(
            f"{event.get('timestamp', '?')} | {event.get('status', '?')} | "
            f"{event.get('operation', '?')} | {event.get('target', '?')}"
        )
        if event.get("error"):
            events.append(f"  {event['error']}")
    _message("Operation history (latest events)", "\n".join(events[-30:]) or "No readable events.")


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

def _run_restore_gauge(
    title: str,
    description: str,
    operation: Callable[[Callable[[int, int], None]], Any],
) -> Any:
    gauge = subprocess.Popen(
        ["dialog", "--title", title, "--gauge", description, "10", "76", "0"],
        stdin=subprocess.PIPE, text=True,
    )
    def report_progress(done: int, total: int) -> None:
        if gauge.poll() is not None or gauge.stdin is None:
            raise DiskRestoreCancelled("progress dialog closed; restore was cancelled")
        percent = min(99, int(done * 100 / total)) if total else 0
        gauge.stdin.write(f"XXX\n{percent}\nProgress {done:,} of {total:,}\nXXX\n")
        gauge.stdin.flush()
    try:
        result = operation(report_progress)
        if gauge.stdin is not None:
            try:
                gauge.stdin.write("100\n")
                gauge.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                gauge.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            gauge.stdin = None
        gauge.wait()
        return result
    except (BrokenPipeError, OSError) as exc:
        raise DiskRestoreCancelled(f"restore cancelled because progress dialog closed: {exc}") from exc
    finally:
        if gauge.stdin is not None:
            try:
                gauge.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if gauge.poll() is None:
            gauge.terminate()
            gauge.wait()


def _restore_security_options(manifest: ImageManifest, manifest_filename: str) -> str | None | bool:
    age_required = any(item.encryption == "age" for item in manifest.artifacts)
    if not age_required:
        return None
    identity = _input("age identity", "Path to the private age identity file:")
    return identity or False

def _save_unattended_profile(filename: str, manifest: ImageManifest, target: dict[str, Any]) -> None:
    wwn = str(target.get("wwn") or "").strip() or None
    serial = str(target.get("serial") or "").strip() or None
    try:
        selector = RestoreTargetSelector(wwn=wwn, serial=serial)
    except RestoreProfileError as exc:
        _message("Cannot save restore profile", str(exc) + "\nThe selected disk needs a stable WWN or serial number.")
        return
    name = _input("Restore profile", "Profile name:")
    if not name:
        return
    default_expiry = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expires_at = _input("Profile expiry", "Expiry timestamp (ISO-8601 with timezone):", default_expiry)
    if not expires_at:
        return
    action = _menu("After successful restore", "Choose the action after read-back verification.", [
        ("none", "Return to the rescue menu"),
        ("reboot", "Reboot"),
        ("poweroff", "Power off"),
    ])
    if action is None:
        return
    initial_path = f"/mnt/restore-media/profiles/{manifest.image_id}.json"
    destination = _input(
        "Profile destination",
        "Absolute path on persistent mounted storage. The directory must already exist:",
        initial_path,
    )
    if not destination:
        return
    try:
        profile = RestoreProfile(
            profile_id=str(uuid.uuid4()),
            name=name,
            image_manifest=filename,
            target=selector,
            execution_mode="unattended",
            layout_policy="preserve",
            verify_after_restore=True,
            on_success=action,
            expires_at=expires_at,
            single_use=True,
        )
        saved = save_unattended_restore_profile(
            profile, destination,
        )
        _message(
            "Restore profile saved",
            f"Root-authorized, single-use profile created:\n{saved}\n\n"
            "Keep the profile, image and replay ledger on persistent storage. The profile and its directory must remain root-owned and protected. "
            "Proportional resizing is not yet supported by the unattended executor.",
        )
    except (RestoreProfileError, OSError) as exc:
        _message("Profile creation failed", str(exc))


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

    if manifest.image_type == "disk":
        action = _menu("Disk image restore", "Choose the scope of the restore.", [
            ("whole-disk", "Restore the complete disk image"),
            ("proportional", "Shrink a verified staging copy and restore to a smaller disk (GPT/ext/NTFS)"),
            ("single-partition", "Extract and restore one selected partition only"),
            ("cancel", "Cancel"),
        ])
        if action not in {"whole-disk", "proportional", "single-partition"}:
            return
    else:
        action = "partition-image"

    target_kind = "disk" if action in {"whole-disk", "proportional"} else "part"
    target = _select_device(
        inventory, target_kind, "Restore target",
        "Select the destination. ALL DATA ON IT WILL BE OVERWRITTEN.",
    )
    if target is None:
        return

    if action == "whole-disk":
        profile_action = _menu("Restore execution", "Execute now or save choices as a root-authorized unattended profile.", [
            ("execute", "Restore now (interactive confirmation)"),
            ("save-profile", "Save root-authorized unattended profile"),
            ("cancel", "Cancel"),
        ])
        if profile_action == "save-profile":
            _save_unattended_profile(filename, manifest, target)
            return
        if profile_action != "execute":
            return

    source_for_proportional = None
    selected_target_identity = None
    if action == "proportional":
        source_for_proportional = _select_device(
            inventory, "disk", "Proportional restore - source",
            "Select the original offline source disk represented by this image. It is probed read-only.",
        )
        if source_for_proportional is None or source_for_proportional.get("path") == target.get("path"):
            _message("Proportional restore cancelled", "Source and destination must be different physical disks.")
            return
        try:
            target_stat = os.stat(target["path"])
            if not stat.S_ISBLK(target_stat.st_mode):
                raise OSError("selected destination is not a block device")
            selected_target_identity = target_stat.st_rdev
        except OSError as exc:
            _message("Proportional restore blocked", f"Cannot capture destination identity: {exc}")
            return

    partition_selector = None
    if action == "single-partition":
        partition_selector = _input(
            "Select source partition",
            "Enter the source partition's PARTUUID, partition name or /dev node from the image.",
        )
        if not partition_selector:
            return

    security = _restore_security_options(manifest, filename)
    if security is False:
        return
    age_identity = security
    phrase = f"ERASE {target['path']}"
    typed = None
    if action != "proportional":
        typed = _input(
            "Destructive confirmation",
            f"Image: {manifest.image_id}\nTarget: {target['path']}\nType exactly:\n{phrase}",
        )
        if typed != phrase:
            _message("Restore cancelled", "The confirmation did not match. No write was started.")
            return

    try:
        if action == "proportional":
            target_size = target.get("size_bytes")
            source_size = source_for_proportional.get("size_bytes")
            if (not isinstance(target_size, int) or not isinstance(source_size, int)
                    or target_size >= manifest.source_size_bytes
                    or source_size != manifest.source_size_bytes
                    or target.get("logical_sector_size") != manifest.logical_sector_size
                    or source_for_proportional.get("logical_sector_size") != manifest.logical_sector_size):
                raise ProportionalRestoreWorkflowError(
                    "source and destination capacities/sector sizes do not match the image geometry; "
                    "destination must be smaller and source must match the captured disk"
                )
            with stage_verified_raw_disk_image(
                manifest, _repository(), age_identity_file=age_identity,
            ) as staged:
                partition_plan = []
                def collect_partition_plan(plans):
                    for plan in plans:
                        partition_plan.append(
                            f"{plan.node} | PARTUUID {plan.partuuid} | "
                            f"start {plan.start_sector} | sectors {plan.size_sectors} | "
                            f"minimum FS {plan.minimum_size_bytes:,} bytes"
                        )
                prepared = prepare_from_offline_source_disk(
                    staged, source_for_proportional,
                    target_size_bytes=target_size,
                    sector_size=manifest.logical_sector_size,
                    plan_callback=collect_partition_plan,
                )
                summary = (
                    f"Image: {manifest.image_id}\n"
                    f"Offline source (read-only probes): {source_for_proportional['path']}\n"
                    f"Destination: {target['path']}\n"
                    f"Original image: {staged.size_bytes:,} bytes\n"
                    f"Prepared image: {prepared.size_bytes:,} bytes\n"
                    f"Destination capacity: {target_size:,} bytes\n"
                    "Filesystem shrink and GPT rewrite were performed only on a private staging copy.\n"
                    "The original source disk and repository artifact have not been modified.\n"
                    "Planned partitions:\n" + "\n".join(partition_plan)
                )
                _message("Proportional restore review", summary)
                typed_proportional = _input(
                    "Destructive confirmation",
                    summary + f"\n\nType exactly:\nERASE {target['path']}",
                )
                if typed_proportional != f"ERASE {target['path']}":
                    _message("Restore cancelled", "Confirmation did not match. No destination write was started.")
                    return
                _run_logged(
                    "restore_proportional_disk", target["path"], manifest.image_id,
                    lambda: restore_staged_proportional_image(
                        prepared, target["path"],
                        sector_size=manifest.logical_sector_size,
                        expected_device_identity=selected_target_identity,
                        confirmation=typed_proportional,
                    ),
                )
        elif action == "whole-disk":
            _run_logged("restore_disk", target["path"], manifest.image_id, lambda: _run_restore_gauge(
                "Restoring whole disk",
                f"Writing image to {target['path']}. ALL EXISTING DATA WILL BE OVERWRITTEN.",
                lambda progress: restore_disk(
                    filename, _repository(), target["path"], confirmation=typed,
                    progress_callback=progress, age_identity_file=age_identity,

                ),
            ))
        elif action == "single-partition":
            def extract(progress):
                return extract_partition_image(
                    filename, _repository(), partition_selector,
                    age_identity_file=age_identity,

                    progress_callback=progress,
                )
            extracted_manifest, extracted_filename = _run_logged(
                "extract_disk_image_partition", target["path"], manifest.image_id,
                lambda: _run_restore_gauge(
                    "Extracting source partition",
                    f"Verifying disk image and extracting {partition_selector}.",
                    extract,
                ),
            )
            _run_logged(
                "restore_partition_from_disk_image", target["path"], extracted_manifest.image_id,
                lambda: _run_restore_gauge(
                    "Restoring selected partition",
                    f"Writing extracted partition to {target['path']}. Other partitions are untouched.",
                    lambda progress: restore_partition(
                        extracted_filename, _repository(), target["path"],
                        confirmation=typed, progress_callback=progress,
                    ),
                ),
            )
        else:
            _run_logged("restore_partition", target["path"], manifest.image_id, lambda: _run_restore_gauge(
                "Restoring partition",
                f"Writing {manifest.artifacts[0].format} image to {target['path']}. ALL DATA ON IT WILL BE OVERWRITTEN.",
                lambda progress: restore_partition(
                    filename, _repository(), target["path"], confirmation=typed,
                    progress_callback=progress, age_identity_file=age_identity,

                ),
            ))
        _message(
            "Restore completed",
            f"Restore utility completed successfully for {target['path']}.\n"
            "Verify the resulting system before relying on it.",
        )
    except (DiskRestoreCancelled, PartitionRestoreCancelled) as exc:
        _message("Restore cancelled", str(exc) + "\nThe target may contain a partial restore and must not be used.")
    except (DiskRestoreError, PartitionRestoreError, DiskImagePartitionError,
            StagedProportionalRestoreError, ProportionalRestoreWorkflowError, ProportionalStagingError,
            OperationLogError, OSError) as exc:
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
            ("volume-topology", "Inspect LVM, LUKS, Stratis and Btrfs topology (read only)"),
            ("capture-disk", "Capture a whole disk"),
            ("capture-partition", "Capture a partition"),
            ("restore", "Restore an image"),
            ("clone-disk", "Clone one local disk directly to another"),
            ("clone-partition", "Clone one partition directly to another"),
            ("history", "View persistent operation history"),
            ("exit", "Return to operating mode selector"),
        ])
        if choice in (None, "exit"):
            return 0
        if choice == "inspect":
            selected = _select_device(inventory, "disk", "Storage inventory", "Select a disk to inspect.")
            if selected:
                _message("Device details - read only", device_details(selected))
        elif choice == "volume-topology":
            _message("Volume topology - read only", volume_topology_details(inventory))
        elif choice == "capture-disk":
            _capture_disk(inventory)
        elif choice == "capture-partition":
            _capture_partition(inventory)
        elif choice == "restore":
            _restore(inventory)
        elif choice == "clone-disk":
            _clone_disk(inventory)
        elif choice == "clone-partition":
            _clone_partition(inventory)
        elif choice == "history":
            _show_operation_log()

if __name__ == "__main__":
    raise SystemExit(main())
