"""Local rescue UI for inspection, capture and verified image restoration."""
from __future__ import annotations
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from feclora.storage.capture import CaptureCancelled
from feclora.storage.disk_capture import DiskCaptureError, capture_disk
from feclora.storage.disk_clone import DiskCloneCancelled, DiskCloneError, clone_disk
from feclora.storage.disk_restore import DiskRestoreCancelled, DiskRestoreError, restore_disk
from feclora.storage.image_manifest import ImageManifest, ManifestValidationError
from feclora.storage.inventory import InventoryError, collect_inventory
from feclora.storage.partition_image_capture import PartitionImageCaptureError, capture_partition_image
from feclora.storage.partition_restore import PartitionRestoreCancelled, PartitionRestoreError, restore_partition
from feclora.storage.operation_log import DEFAULT_LOG_PATH, OperationLogError, operation_record

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

def _compression() -> tuple[str, int | None] | None:
    tool = _menu("Image compression", "Choose compression tool. No compression is also available.", [
        ("none", "None (fastest, largest)"),
        ("gzip", "gzip"),
        ("xz", "xz"),
    ])
    if tool is None:
        return None
    if tool == "none":
        return ("none", None)
    levels = [("1", "1 - fastest"), ("3", "3 - fast"), ("6", "6 - balanced"), ("9", "9 - maximum")]
    if tool == "xz":
        levels = [("0", "0 - fastest"), ("3", "3 - fast"), ("6", "6 - balanced"), ("9", "9 - maximum")]
    selected = _menu(f"{tool} compression level", "Higher levels use more CPU and usually produce smaller images.", levels)
    return (tool, int(selected)) if selected is not None else None


def _image_security_options() -> tuple[str | None, str | None] | None:
    mode = _menu("Image security", "Choose optional image encryption and manifest signing.", [
        ("none", "Neither encryption nor signature"),
        ("age", "Encrypt with age"),
        ("minisign", "Sign manifest with minisign"),
        ("both", "Encrypt with age and sign with minisign"),
    ])
    if mode is None:
        return None
    recipients = None
    secret_key = None
    if mode in {"age", "both"}:
        recipients = _input("age recipients", "Path to recipients file (public age keys, one per line):")
        if not recipients:
            return None
    if mode in {"minisign", "both"}:
        secret_key = _input("minisign signing key", "Path to minisign secret key:")
        if not secret_key:
            return None
    return recipients, secret_key

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
    if security is None:
        return
    recipients, signing_key = security
    try:
        manifest = _run_logged("capture_disk", source["path"], image_id, lambda: _run_capture_gauge(
            "Capturing whole disk", f"Reading {source['path']} into image repository.",
            lambda progress: capture_disk(
                source["path"], image_id, _repository(), compression=compression,
                compression_level=compression_level, age_recipients_file=recipients,
                minisign_secret_key=signing_key, progress_callback=progress,
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
                age_recipients_file=recipients, minisign_secret_key=signing_key,
                progress_callback=progress,
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
    _message("Operation history (latest events)", "\\n".join(events[-30:]) or "No readable events.")


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
        gauge.stdin.write(f"XXX\n{percent}\nWritten {done:,} of {total:,} bytes\nXXX\n")
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


def _restore_security_options(manifest: ImageManifest, manifest_filename: str) -> tuple[str | None, str | None, bool] | None:
    age_required = any(item.encryption == "age" for item in manifest.artifacts)
    identity = None
    if age_required:
        identity = _input("age identity", "Path to the private age identity file:")
        if not identity:
            return None
    signature = os.path.join(_repository(), manifest_filename + ".minisig")
    public_key = None
    require_signature = False
    if os.path.lexists(signature):
        choice = _menu("Manifest signature", "This image has a detached minisign signature.", [
            ("verify", "Verify with a trusted public key"),
            ("skip", "Continue without signature verification"),
        ])
        if choice is None:
            return None
        if choice == "verify":
            public_key = _input("minisign public key", "Path to independently trusted minisign public key:")
            if not public_key:
                return None
            require_signature = True
        else:
            _message("Signature not verified", "The image will be restored without establishing publisher authenticity.")
    return identity, public_key, require_signature

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
    security = _restore_security_options(manifest, filename)
    if security is None:
        return
    age_identity, minisign_public_key, require_signature = security
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
            _run_logged("restore_disk", target["path"], manifest.image_id, lambda: _run_restore_gauge(
                "Restoring whole disk", f"Writing image to {target['path']}. ALL EXISTING DATA WILL BE OVERWRITTEN.",
                lambda progress: restore_disk(
                    filename, _repository(), target["path"], confirmation=typed,
                    progress_callback=progress, age_identity_file=age_identity,
                    minisign_public_key=minisign_public_key, require_signature=require_signature,
                ),
            ))
        else:
            _run_logged("restore_partition", target["path"], manifest.image_id, lambda: _run_restore_gauge(
                "Restoring partition",
                f"Writing {manifest.artifacts[0].format} image to {target['path']}. ALL EXISTING DATA WILL BE OVERWRITTEN.",
                lambda progress: restore_partition(
                    filename, _repository(), target["path"], confirmation=typed,
                    progress_callback=progress, age_identity_file=age_identity,
                    minisign_public_key=minisign_public_key, require_signature=require_signature,
                ),
            ))
        _message("Restore completed", f"Restore utility completed successfully for {target['path']}.\nVerify the resulting system before relying on it.")
    except (DiskRestoreCancelled, PartitionRestoreCancelled) as exc:
        _message("Restore cancelled", str(exc) + "\nThe target may contain a partial restore and must not be used.")
    except (DiskRestoreError, PartitionRestoreError, OperationLogError, OSError) as exc:
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
            ("history", "View persistent operation history"),
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
        elif choice == "history":
            _show_operation_log()

if __name__ == "__main__":
    raise SystemExit(main())
