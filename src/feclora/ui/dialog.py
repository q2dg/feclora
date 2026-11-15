"""Shared terminal-dialog and device-selection primitives for Feclora UIs."""
from __future__ import annotations

import subprocess
from typing import Any, Callable

from feclora.storage.capture import CaptureCancelled
from feclora.storage.disk_restore import DiskRestoreCancelled


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
