"""Offline NTFS shrinking on a loop slice backed only by private staging."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .source_safety import SourceSafetyError, check_capture_source_safe
from .proportional_staging import StagedRawDiskImage


class StagedNTFSShrinkError(RuntimeError):
    """A private staged NTFS filesystem could not be shrunk and verified safely."""


def _digest_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reported_bytes(output: str, label: str) -> int:
    matches = re.findall(
        rf"^{re.escape(label)}:?\s*([\d,]+)\s+bytes",
        output,
        re.IGNORECASE | re.MULTILINE,
    )
    if len(matches) != 1:
        raise StagedNTFSShrinkError(
            f"ntfsresize did not report one unambiguous {label.lower()}"
        )
    value = int(matches[0].replace(",", ""))
    if value <= 0:
        raise StagedNTFSShrinkError(f"ntfsresize returned an invalid {label.lower()}")
    return value


def shrink_staged_ntfs_filesystem(
    staged: StagedRawDiskImage,
    *,
    partition_start_sector: int,
    source_partition_size_sectors: int,
    target_partition_size_bytes: int,
    target_filesystem_size_bytes: int,
    sector_size: int,
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    block_device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    timeout: int = 1800,
) -> StagedRawDiskImage:
    """Shrink NTFS inside an exact loop slice backed by a verified private RAW file.

    This does not edit GPT, truncate the RAW image, or access a destination
    block device. ntfsresize is deliberately invoked without --force: dirty,
    hibernated or otherwise unsupported NTFS volumes must fail closed.
    """
    if not isinstance(staged, StagedRawDiskImage):
        raise StagedNTFSShrinkError("a verified private staged RAW image is required")
    values = (
        partition_start_sector, source_partition_size_sectors,
        target_partition_size_bytes, target_filesystem_size_bytes, sector_size,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise StagedNTFSShrinkError("partition geometry and sizes must be integers")
    if (partition_start_sector < 1 or source_partition_size_sectors <= 0
            or sector_size not in {512, 4096}
            or target_partition_size_bytes <= 0 or target_filesystem_size_bytes <= 0):
        raise StagedNTFSShrinkError("partition geometry or target size is invalid")
    offset = partition_start_sector * sector_size
    source_partition_bytes = source_partition_size_sectors * sector_size
    if (offset + source_partition_bytes > staged.size_bytes
            or target_partition_size_bytes >= source_partition_bytes
            or target_filesystem_size_bytes > target_partition_size_bytes):
        raise StagedNTFSShrinkError("requested filesystem/partition size exceeds staged source geometry")
    if not isinstance(staged.path, str) or not os.path.isabs(staged.path) or "\x00" in staged.path:
        raise StagedNTFSShrinkError("staged image path is invalid")

    parent, basename = os.path.dirname(staged.path), os.path.basename(staged.path)
    try:
        directory_fd = os.open(
            parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
            getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            directory = os.fstat(directory_fd)
            file_info = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
            if (not stat.S_ISDIR(directory.st_mode) or directory.st_mode & 0o077
                    or directory.st_uid != os.geteuid()
                    or not stat.S_ISREG(file_info.st_mode) or file_info.st_mode & 0o077
                    or file_info.st_nlink != 1 or file_info.st_uid != os.geteuid()
                    or file_info.st_size != staged.size_bytes):
                raise StagedNTFSShrinkError("staged RAW is not a private owned single-link file")
            fd = os.open(basename, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev != file_info.st_dev or opened.st_ino != file_info.st_ino
                        or opened.st_nlink != 1 or opened.st_size != staged.size_bytes):
                    raise StagedNTFSShrinkError("staged RAW identity changed during preflight")
            finally:
                os.close(fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise StagedNTFSShrinkError(f"cannot validate private staged RAW: {exc}") from exc
    try:
        if _digest_file(staged.path) != staged.sha256:
            raise StagedNTFSShrinkError("staged RAW digest mismatch before NTFS shrink")
    except OSError as exc:
        raise StagedNTFSShrinkError(f"cannot hash staged RAW before NTFS shrink: {exc}") from exc

    resolve = which or shutil.which
    run = runner or subprocess.run
    available = executables or {}
    required = {
        name: available.get(name) or resolve(name)
        for name in ("losetup", "blkid", "ntfsresize", "blockdev")
    }
    missing = [name for name, executable in required.items() if not executable]
    if missing:
        raise StagedNTFSShrinkError("required staged NTFS tools are missing: " + ", ".join(missing))
    uid = effective_uid or os.geteuid

    def invoke(name: str, args: list[str], *, command_timeout: int | None = None) -> Any:
        try:
            argv = privileged_argv([required[name], *args], effective_uid=uid, which=resolve)
            return run(argv, check=True, capture_output=True, text=True,
                       timeout=command_timeout or timeout)
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise StagedNTFSShrinkError(
                f"{name} failed during staged NTFS shrink: {exc}"
            ) from exc

    loop_device: str | None = None
    primary_error: BaseException | None = None
    try:
        attached = invoke("losetup", [
            "--find", "--show", "--offset", str(offset),
            "--sizelimit", str(source_partition_bytes), staged.path,
        ], command_timeout=60)
        loop_device = (attached.stdout or "").strip()
        if not re.fullmatch(r"/dev/loop[0-9]+", loop_device):
            raise StagedNTFSShrinkError("losetup returned an unexpected loop-device path")
        validator = block_device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
        try:
            if not validator(loop_device):
                raise StagedNTFSShrinkError("created loop path is not a block device")
        except OSError as exc:
            raise StagedNTFSShrinkError(f"cannot verify created loop device: {exc}") from exc

        mapping = invoke("losetup", [
            "--list", "--json", "--output", "NAME,BACK-FILE,OFFSET,SIZELIMIT", loop_device,
        ], command_timeout=30)
        try:
            entries = json.loads(mapping.stdout).get("loopdevices")
            if not isinstance(entries, list) or len(entries) != 1:
                raise ValueError("unexpected loop-device list")
            entry = entries[0]
            name = entry.get("name") or entry.get("NAME")
            backing = entry.get("back-file") or entry.get("back_file") or entry.get("BACK-FILE")
            actual_offset = entry.get("offset") if "offset" in entry else entry.get("OFFSET")
            actual_limit = entry.get("sizelimit") if "sizelimit" in entry else entry.get("SIZELIMIT")
            if (name != loop_device or not isinstance(backing, str)
                    or os.path.realpath(backing) != os.path.realpath(staged.path)
                    or int(actual_offset) != offset or int(actual_limit) != source_partition_bytes):
                raise ValueError("loop mapping does not match requested staged partition geometry")
        except (TypeError, ValueError, AttributeError, json.JSONDecodeError) as exc:
            raise StagedNTFSShrinkError(
                f"loop backing mapping failed read-back validation: {exc}"
            ) from exc

        try:
            if safety_check is None:
                check_capture_source_safe(loop_device, runner=run, which=resolve)
            else:
                safety_check(loop_device)
        except (SourceSafetyError, OSError, subprocess.SubprocessError) as exc:
            raise StagedNTFSShrinkError(
                f"loop partition must be offline and unused: {exc}"
            ) from exc

        detected = invoke(
            "blkid", ["-p", "-s", "TYPE", "-o", "value", loop_device],
            command_timeout=60,
        ).stdout.strip().lower()
        if detected not in {"ntfs", "ntfs3"}:
            raise StagedNTFSShrinkError(
                f"staged NTFS shrink requires NTFS; detected {detected or 'unknown'}"
            )
        capacity = int(invoke(
            "blockdev", ["--getsize64", loop_device], command_timeout=60
        ).stdout.strip())
        if capacity != source_partition_bytes:
            raise StagedNTFSShrinkError("loop partition capacity differs from source GPT geometry")

        before = invoke("ntfsresize", ["--info", loop_device])
        before_output = (before.stdout or "") + "\n" + (before.stderr or "")
        minimum_bytes = _reported_bytes(before_output, "You might resize at")
        current_bytes = _reported_bytes(before_output, "Current volume size")
        if target_filesystem_size_bytes >= current_bytes:
            raise StagedNTFSShrinkError("NTFS target must be smaller than the current filesystem")
        if target_filesystem_size_bytes < minimum_bytes:
            raise StagedNTFSShrinkError("NTFS target is below the staged filesystem minimum")

        invoke("ntfsresize", [
            "--size", str(target_filesystem_size_bytes), loop_device,
        ], command_timeout=timeout)

        after = invoke("ntfsresize", ["--info", loop_device])
        after_output = (after.stdout or "") + "\n" + (after.stderr or "")
        verified_current = _reported_bytes(after_output, "Current volume size")
        verified_minimum = _reported_bytes(after_output, "You might resize at")
        if (verified_current > target_filesystem_size_bytes
                or verified_current <= 0 or verified_minimum > verified_current):
            raise StagedNTFSShrinkError("NTFS filesystem size failed post-shrink read-back")
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if loop_device is not None:
            try:
                invoke("losetup", ["--detach", loop_device], command_timeout=60)
            except BaseException as detach_exc:
                if primary_error is None:
                    raise StagedNTFSShrinkError(
                        f"NTFS operation ended but loop device could not be detached: {detach_exc}"
                    ) from detach_exc
                raise StagedNTFSShrinkError(
                    f"{primary_error}; additionally, loop device {loop_device} "
                    f"could not be detached and may remain attached: {detach_exc}"
                ) from primary_error

    try:
        output_digest = _digest_file(staged.path)
    except OSError as exc:
        raise StagedNTFSShrinkError(f"cannot hash staged RAW after NTFS shrink: {exc}") from exc
    if output_digest == staged.sha256:
        raise StagedNTFSShrinkError("NTFS shrink reported success but staged RAW bytes did not change")
    return StagedRawDiskImage(staged.path, staged.size_bytes, output_digest)
