"""Direct local whole-disk cloning with fail-closed source and target checks."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .source_safety import SourceSafetyError, check_capture_source_safe


class DiskCloneError(RuntimeError):
    """A direct disk clone was rejected or failed."""


def _geometry(path: str, lsblk: str, runner: Callable[..., Any]) -> tuple[int, int, bool, str]:
    try:
        result = runner(
            [lsblk, "--bytes", "--noheadings", "--nodeps", "--output",
             "SIZE,TYPE,LOG-SEC,RO,PTTYPE", path],
            check=True, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiskCloneError(f"cannot inspect disk {path}: {exc}") from exc
    fields = result.stdout.split()
    if len(fields) != 5 or fields[1] != "disk":
        raise DiskCloneError(f"{path} is not exactly one whole disk")
    try:
        size, sector = int(fields[0]), int(fields[2])
    except ValueError as exc:
        raise DiskCloneError(f"lsblk returned invalid geometry for {path}") from exc
    read_only = fields[3] == "1"
    if size <= 0 or sector not in {512, 4096}:
        raise DiskCloneError(f"disk geometry is invalid or unsupported for {path}")
    return size, sector, read_only, fields[4].lower()


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

    stderr = tempfile.TemporaryFile(mode="w+b")
    process = None
    try:
        factory = popen_factory or subprocess.Popen
        try:
            process = factory(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=stderr, close_fds=True,
            )
        except (OSError, PrivilegeError) as exc:
            raise DiskCloneError(f"could not start dd: {exc}") from exc
        return_code = process.wait()
        if return_code != 0:
            stderr.seek(0)
            detail = stderr.read(8192).decode("utf-8", errors="replace").strip()
            raise DiskCloneError(
                f"dd exited with status {return_code}" + (f": {detail}" if detail else "")
            )
        if source_pttype == "gpt" and target_size > source_size:
            try:
                repair = privileged_argv([sgdisk, "-e", target_path], effective_uid=effective_uid)
                run(repair, check=True, capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
                raise DiskCloneError(f"disk data copied but backup GPT relocation failed: {exc}") from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        stderr.close()
    return source_size
