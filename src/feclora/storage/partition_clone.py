"""Direct, verified local partition-to-partition cloning."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .source_safety import SourceSafetyError, check_capture_source_safe


class PartitionCloneError(RuntimeError):
    """A partition clone was rejected or failed."""


class PartitionCloneCancelled(PartitionCloneError):
    """The operator cancelled a running partition clone."""


def _geometry(path: str, lsblk: str, runner: Callable[..., Any]) -> tuple[int, int, bool]:
    try:
        result = runner(
            [lsblk, "--json", "--bytes", "--nodeps", "--output",
             "SIZE,TYPE,LOG-SEC,RO", path],
            check=True, capture_output=True, text=True, timeout=20,
        )
        payload = json.loads(result.stdout)
        devices = payload["blockdevices"]
        if not isinstance(devices, list) or len(devices) != 1:
            raise ValueError("expected exactly one block device")
        device = devices[0]
        if device.get("type") != "part":
            raise ValueError("device is not a partition")
        size = int(device["size"])
        sector = int(device["log-sec"])
        read_only = bool(device.get("ro", False))
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PartitionCloneError(f"cannot inspect partition geometry for {path}: {exc}") from exc
    if size <= 0 or sector not in {512, 4096}:
        raise PartitionCloneError(f"partition geometry is invalid or unsupported for {path}")
    return size, sector, read_only


def _backing_disks(path: str, lsblk: str, runner: Callable[..., Any]) -> set[str]:
    try:
        result = runner(
            [lsblk, "--json", "--tree", "--paths", "--inverse", "--output", "PATH,TYPE", path],
            check=True, capture_output=True, text=True, timeout=20,
        )
        roots = json.loads(result.stdout)["blockdevices"]
        disks: set[str] = set()
        def visit(nodes):
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValueError("invalid block-device node")
                if node.get("type") == "disk" and isinstance(node.get("path"), str):
                    disks.add(os.path.realpath(node["path"]))
                children = node.get("children") or []
                if not isinstance(children, list):
                    raise ValueError("invalid block-device children")
                visit(children)
        if not isinstance(roots, list) or not roots:
            raise ValueError("empty inverse block-device graph")
        visit(roots)
        if not disks:
            raise ValueError("no physical backing disk found")
        return disks
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PartitionCloneError(f"cannot trace physical backing disks for {path}: {exc}") from exc


def _stop(process: Any) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except (TypeError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()


def _read_digest(
    dd: str, target: str, expected_size: int, *,
    factory: Callable[..., Any], effective_uid: Callable[[], int] | None,
) -> str:
    command = privileged_argv(
        [dd, f"if={target}", "bs=4M", "iflag=count_bytes",
         f"count={expected_size}", "status=none"],
        effective_uid=effective_uid,
    )
    stderr = tempfile.TemporaryFile(mode="w+b")
    process = None
    try:
        process = factory(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=stderr, close_fds=True,
        )
        if process.stdout is None:
            raise PartitionCloneError("read-back dd did not provide stdout")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = process.stdout.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        process.stdout.close()
        result = process.wait()
        if result != 0 or total != expected_size:
            stderr.seek(0)
            detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
            raise PartitionCloneError("destination read-back failed" + (f": {detail}" if detail else ""))
        return digest.hexdigest()
    finally:
        _stop(process)
        stderr.close()


def clone_partition(
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
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    """Copy one complete source partition into a selected equal-or-larger target."""
    for label, path in (("source", source_path), ("target", target_path)):
        if not isinstance(path, str) or not path.startswith("/dev/") or "\x00" in path:
            raise PartitionCloneError(f"{label} must be an absolute /dev/ path")
    if source_path == target_path:
        raise PartitionCloneError("source and target must be different partitions")
    expected_confirmation = f"ERASE {target_path} FROM {source_path}"
    if confirmation != expected_confirmation:
        raise PartitionCloneError(f"explicit confirmation required: {expected_confirmation}")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(source_path) or not validator(target_path):
            raise PartitionCloneError("source and target must both be accessible block devices")
        source_rdev = os.stat(source_path).st_rdev if device_validator is None else None
        target_rdev = os.stat(target_path).st_rdev if device_validator is None else None
        if source_rdev is not None and source_rdev == target_rdev:
            raise PartitionCloneError("source and target resolve to the same block device")
    except OSError as exc:
        raise PartitionCloneError(f"cannot inspect source or target device: {exc}") from exc

    available = executables or {}
    lsblk = available.get("lsblk") or shutil.which("lsblk")
    dd = available.get("dd") or shutil.which("dd")
    if not lsblk or not dd:
        raise PartitionCloneError("lsblk and dd are required for partition cloning")
    run = runner or subprocess.run
    source_size, source_sector, source_ro = _geometry(source_path, lsblk, run)
    target_size, target_sector, target_ro = _geometry(target_path, lsblk, run)
    if source_ro and target_ro:
        raise PartitionCloneError("both selected partitions are read-only")
    if target_ro:
        raise PartitionCloneError("target partition is marked read-only")
    if source_sector != target_sector:
        raise PartitionCloneError("source and target logical sector sizes differ")
    if target_size < source_size:
        raise PartitionCloneError("target partition is smaller than source partition")
    if _backing_disks(source_path, lsblk, run) & _backing_disks(target_path, lsblk, run):
        raise PartitionCloneError("source and target share a physical backing disk")

    safety = device_safety_check or check_capture_source_safe
    try:
        safety(source_path)
        safety(target_path)
        if not validator(source_path) or not validator(target_path):
            raise PartitionCloneError("source or target partition is no longer valid")
        if source_rdev is not None and os.stat(source_path).st_rdev != source_rdev:
            raise PartitionCloneError("source partition identity changed")
        if target_rdev is not None and os.stat(target_path).st_rdev != target_rdev:
            raise PartitionCloneError("target partition identity changed")
        safety(source_path)
        safety(target_path)
    except SourceSafetyError as exc:
        raise PartitionCloneError(f"source or target is unsafe: {exc}") from exc
    except OSError as exc:
        raise PartitionCloneError(f"cannot revalidate source or target: {exc}") from exc

    factory = popen_factory or subprocess.Popen
    source_process = target_process = None
    source_stderr = tempfile.TemporaryFile(mode="w+b")
    target_stderr = tempfile.TemporaryFile(mode="w+b")
    digest = hashlib.sha256()
    copied = 0
    try:
        source_argv = privileged_argv(
            [dd, f"if={source_path}", "bs=4M", "iflag=count_bytes",
             f"count={source_size}", "status=none"],
            effective_uid=effective_uid,
        )
        target_argv = privileged_argv(
            [dd, f"of={target_path}", "bs=4M", "conv=fsync", "status=none"],
            effective_uid=effective_uid,
        )
        source_process = factory(
            source_argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=source_stderr, close_fds=True,
        )
        target_process = factory(
            target_argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=target_stderr, close_fds=True,
        )
        if source_process.stdout is None or target_process.stdin is None:
            raise PartitionCloneError("dd processes did not provide required pipes")
        while copied < source_size:
            if progress_callback is not None:
                # Callback may raise PartitionCloneCancelled to stop the operation.
                progress_callback(copied, source_size)
            chunk = source_process.stdout.read(min(1024 * 1024, source_size - copied))
            if not chunk:
                raise PartitionCloneError("source dd ended before the expected partition size")
            view = memoryview(chunk)
            written = 0
            while written < len(view):
                count = target_process.stdin.write(view[written:])
                if count is None or count <= 0:
                    raise PartitionCloneError("target dd stopped accepting partition data")
                digest.update(view[written:written + count])
                written += count
            copied += len(chunk)
        if source_process.stdout.read(1):
            raise PartitionCloneError("source dd produced more bytes than requested")
        source_process.stdout.close()
        target_process.stdin.close()
        source_rc = source_process.wait()
        target_rc = target_process.wait()
        if source_rc != 0 or target_rc != 0:
            raise PartitionCloneError(f"dd failed (source={source_rc}, target={target_rc})")
        if progress_callback is not None:
            progress_callback(source_size, source_size)
        readback = _read_digest(
            dd, target_path, source_size, factory=factory, effective_uid=effective_uid
        )
        if readback != digest.hexdigest():
            raise PartitionCloneError("destination read-back SHA-256 does not match source")
        return copied
    except PartitionCloneCancelled:
        _stop(source_process)
        _stop(target_process)
        raise
    except (BrokenPipeError, OSError, subprocess.SubprocessError, PrivilegeError) as exc:
        _stop(source_process)
        _stop(target_process)
        raise PartitionCloneError(f"partition clone failed: {exc}") from exc
    finally:
        _stop(source_process)
        _stop(target_process)
        source_stderr.close()
        target_stderr.close()
