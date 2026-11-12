"""Direct local whole-disk cloning with fail-closed source and target checks."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .process_control import stop_process
from .source_safety import SourceSafetyError, check_capture_source_safe


class DiskCloneError(RuntimeError):
    """A direct disk clone was rejected or failed."""


class DiskCloneCancelled(DiskCloneError):
    """The operator cancelled a running direct disk clone."""


def _geometry(path: str, lsblk: str, runner: Callable[..., Any]) -> tuple[int, int, bool, str]:
    try:
        result = runner(
            [lsblk, "--json", "--bytes", "--nodeps", "--output",
             "SIZE,TYPE,LOG-SEC,RO,PTTYPE", path],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiskCloneError(f"cannot inspect disk {path}: {exc}") from exc
    try:
        payload = json.loads(result.stdout)
        devices = payload["blockdevices"]
        if not isinstance(devices, list) or len(devices) != 1:
            raise ValueError("expected exactly one block device")
        device = devices[0]
        if device.get("type") != "disk":
            raise ValueError("device is not a whole disk")
        size = int(device["size"])
        sector = int(device["log-sec"])
        read_only = bool(device.get("ro", False))
        partition_table = str(device.get("pttype") or "").lower()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DiskCloneError(f"lsblk returned invalid geometry for {path}: {exc}") from exc
    if size <= 0 or sector not in {512, 4096}:
        raise DiskCloneError(f"disk geometry is invalid or unsupported for {path}")
    return size, sector, read_only, partition_table

def _backing_disks(path: str, lsblk: str, runner: Callable[..., Any]) -> set[str]:
    try:
        result = runner(
            [lsblk, "--json", "--tree", "--paths", "--inverse",
             "--output", "PATH,TYPE", path],
            check=True, capture_output=True, text=True, timeout=20,
        )
        payload = json.loads(result.stdout)
        roots = payload["blockdevices"]
        if not isinstance(roots, list) or not roots:
            raise ValueError("empty inverse block-device graph")
        disks: set[str] = set()
        def visit(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValueError("invalid block-device node")
                if node.get("type") == "disk" and isinstance(node.get("path"), str):
                    disks.add(os.path.realpath(node["path"]))
                children = node.get("children") or []
                if not isinstance(children, list):
                    raise ValueError("invalid block-device children")
                visit(children)
        visit(roots)
        if not disks:
            raise ValueError("no physical backing disk found")
        return disks
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DiskCloneError(f"cannot trace physical backing disks for {path}: {exc}") from exc


def clone_disk(
    source_path: str,
    target_path: str,
    *,
    confirmation: str,
    executables: dict[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    runner: Callable[..., Any] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    device_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> int:
    """Clone one offline whole disk directly to another with GNU dd."""
    for label, path in (("source", source_path), ("target", target_path)):
        if not isinstance(path, str) or not path.startswith("/dev/") or "\x00" in path:
            raise DiskCloneError(f"{label} must be an absolute /dev/ path")
    if source_path == target_path:
        raise DiskCloneError("source and target must be different devices")
    if confirmation != f"ERASE {target_path}":
        raise DiskCloneError(f"explicit confirmation required: ERASE {target_path}")

    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(source_path) or not validator(target_path):
            raise DiskCloneError("source and target must both be accessible block devices")
        source_rdev = os.stat(source_path).st_rdev if device_validator is None else None
        target_rdev = os.stat(target_path).st_rdev if device_validator is None else None
        if source_rdev is not None and source_rdev == target_rdev:
            raise DiskCloneError("source and target resolve to the same block device")
    except OSError as exc:
        raise DiskCloneError(f"cannot inspect source or target device: {exc}") from exc

    available = executables or {}
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    dd = available.get("dd") or shutil.which("dd")
    if not lsblk or not dd:
        raise DiskCloneError("lsblk and dd are required for direct disk cloning")
    run = runner or subprocess.run
    source_size, source_sector, source_ro, source_pttype = _geometry(source_path, lsblk, run)
    target_size, target_sector, target_ro, _target_pttype = _geometry(target_path, lsblk, run)
    # A read-only source is safe and useful; only the destination must be writable.
    if target_ro:
        raise DiskCloneError("target disk is marked read-only")
    if source_sector != target_sector:
        raise DiskCloneError("source and target logical sector sizes differ")
    if target_size < source_size:
        raise DiskCloneError("target disk is smaller than source disk")
    source_backing = _backing_disks(source_path, lsblk, run)
    target_backing = _backing_disks(target_path, lsblk, run)
    if source_backing & target_backing:
        raise DiskCloneError("source and target share one or more physical backing disks")

    safety = device_safety_check or check_capture_source_safe
    try:
        safety(source_path)
        safety(target_path)
    except SourceSafetyError as exc:
        raise DiskCloneError(f"source or target is unsafe: {exc}") from exc

    try:
        if not validator(source_path) or not validator(target_path):
            raise DiskCloneError("source or target device is no longer valid")
        if source_rdev is not None and os.stat(source_path).st_rdev != source_rdev:
            raise DiskCloneError("source block-device identity changed")
        if target_rdev is not None and os.stat(target_path).st_rdev != target_rdev:
            raise DiskCloneError("target block-device identity changed")
        safety(source_path)
        safety(target_path)
    except SourceSafetyError as exc:
        raise DiskCloneError(f"source or target became unsafe: {exc}") from exc
    except OSError as exc:
        raise DiskCloneError(f"cannot revalidate source or target: {exc}") from exc

    sgdisk = available.get("sgdisk") or shutil.which("sgdisk")
    if source_pttype == "gpt" and target_size > source_size and not sgdisk:
        raise DiskCloneError("sgdisk is required to relocate the backup GPT header on a larger target")

    command = [
        dd, f"if={source_path}", f"of={target_path}", "bs=4M",
        f"count={source_size}", "iflag=count_bytes", "conv=fsync",
        "status=progress",
    ]
    try:
        argv = privileged_argv(command, effective_uid=effective_uid)
    except PrivilegeError as exc:
        raise DiskCloneError(f"cannot obtain non-interactive root privileges: {exc}") from exc

    process = None
    try:
        factory = popen_factory or subprocess.Popen
        try:
            process = factory(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, close_fds=True,
            )
        except (OSError, PrivilegeError) as exc:
            raise DiskCloneError(f"could not start dd: {exc}") from exc
        progress_buffer = bytearray()
        stderr_tail = bytearray()
        stderr_stream = getattr(process, "stderr", None)
        if stderr_stream is not None:
            while True:
                byte = stderr_stream.read(1)
                if not byte:
                    break
                if len(stderr_tail) >= 8192:
                    del stderr_tail[:1]
                stderr_tail.extend(byte)
                if byte in (b"\r", b"\n"):
                    line = progress_buffer.decode("utf-8", errors="replace").strip()
                    progress_buffer.clear()
                    if progress_callback and line:
                        try:
                            copied = int(line.split()[0].replace(",", ""))
                        except (ValueError, IndexError):
                            continue
                        copied = min(source_size, max(0, copied))
                        progress_callback(copied, source_size, line)
                else:
                    progress_buffer.extend(byte)
        return_code = process.wait()
        if return_code != 0:
            detail = stderr_tail.decode("utf-8", errors="replace").strip()
            raise DiskCloneError(
                f"dd exited with status {return_code}" + (f": {detail}" if detail else "")
            )
        if source_pttype == "gpt" and target_size > source_size:
            try:
                repair = privileged_argv([sgdisk, "-e", target_path], effective_uid=effective_uid)
                run(repair, check=True, capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
                raise DiskCloneError(f"disk data copied but backup GPT relocation failed: {exc}") from exc
    except DiskCloneCancelled:
        stop_process(process)
        raise
    except (BrokenPipeError, OSError) as exc:
        stop_process(process)
        raise DiskCloneCancelled(f"disk clone progress UI closed; operation stopped: {exc}") from exc
    finally:
        stop_process(process)
    return source_size
