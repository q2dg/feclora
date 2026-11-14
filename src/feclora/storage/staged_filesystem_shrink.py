"""Offline ext2/3/4 shrinking on a loop slice backed only by private staging."""
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
from .proportional_staging import StagedRawDiskImage, ProportionalStagingError


class StagedFilesystemShrinkError(RuntimeError):
    """A private staged filesystem could not be shrunk and verified safely."""


def _digest_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def shrink_staged_ext_filesystem(
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
    timeout: int = 900,
) -> StagedRawDiskImage:
    """Shrink one ext filesystem inside a staged RAW image; never touch source/target disks.

    A loop device is created with an exact byte offset and size limit derived
    from the caller's already-inspected GPT geometry. The backing file must be
    a private, single-link regular file owned by this process. The loop mapping
    is independently read back before any filesystem mutation. The function
    does not edit GPT or truncate the image; that is a separate later step.
    """
    if not isinstance(staged, StagedRawDiskImage):
        raise StagedFilesystemShrinkError("a verified private staged RAW image is required")
    integer_values = (
        partition_start_sector, source_partition_size_sectors,
        target_partition_size_bytes, target_filesystem_size_bytes, sector_size,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in integer_values):
        raise StagedFilesystemShrinkError("partition geometry and sizes must be integers")
    if (partition_start_sector < 1 or source_partition_size_sectors <= 0
            or sector_size not in {512, 4096}
            or target_partition_size_bytes <= 0 or target_filesystem_size_bytes <= 0):
        raise StagedFilesystemShrinkError("partition geometry or target size is invalid")
    offset = partition_start_sector * sector_size
    source_partition_bytes = source_partition_size_sectors * sector_size
    if (offset + source_partition_bytes > staged.size_bytes
            or target_partition_size_bytes >= source_partition_bytes
            or target_filesystem_size_bytes > target_partition_size_bytes):
        raise StagedFilesystemShrinkError("requested filesystem/partition size exceeds staged source geometry")
    if target_filesystem_size_bytes % 1024:
        raise StagedFilesystemShrinkError("filesystem target must be aligned to 1024-byte ext blocks")
    if not isinstance(staged.path, str) or not os.path.isabs(staged.path) or "\x00" in staged.path:
        raise StagedFilesystemShrinkError("staged image path is invalid")

    # Pin the private file identity before asking the kernel to attach it.
    parent = os.path.dirname(staged.path)
    basename = os.path.basename(staged.path)
    try:
        dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                         getattr(os, "O_NOFOLLOW", 0))
        try:
            directory = os.fstat(dir_fd)
            file_info = os.stat(basename, dir_fd=dir_fd, follow_symlinks=False)
            if (not stat.S_ISDIR(directory.st_mode) or directory.st_mode & 0o077
                    or directory.st_uid != os.geteuid()
                    or not stat.S_ISREG(file_info.st_mode) or file_info.st_mode & 0o077
                    or file_info.st_nlink != 1 or file_info.st_uid != os.geteuid()
                    or file_info.st_size != staged.size_bytes):
                raise StagedFilesystemShrinkError("staged RAW is not a private owned single-link file")
            fd = os.open(basename, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev != file_info.st_dev or opened.st_ino != file_info.st_ino
                        or opened.st_nlink != 1 or opened.st_size != staged.size_bytes):
                    raise StagedFilesystemShrinkError("staged RAW identity changed during preflight")
            finally:
                os.close(fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise StagedFilesystemShrinkError(f"cannot validate private staged RAW: {exc}") from exc
    try:
        if _digest_file(staged.path) != staged.sha256:
            raise StagedFilesystemShrinkError("staged RAW digest mismatch before filesystem shrink")
    except OSError as exc:
        raise StagedFilesystemShrinkError(f"cannot hash staged RAW before shrink: {exc}") from exc

    resolve = which or shutil.which
    run = runner or subprocess.run
    available = executables or {}
    required = {
        name: available.get(name) or resolve(name)
        for name in ("losetup", "blkid", "e2fsck", "dumpe2fs", "resize2fs")
    }
    missing = [name for name, executable in required.items() if not executable]
    if missing:
        raise StagedFilesystemShrinkError("required staged shrink tools are missing: " + ", ".join(missing))
    uid = effective_uid or os.geteuid

    def invoke(name: str, args: list[str], *, command_timeout: int | None = None) -> Any:
        try:
            argv = privileged_argv([required[name], *args], effective_uid=uid, which=resolve)
            return run(argv, check=True, capture_output=True, text=True,
                       timeout=command_timeout or timeout)
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise StagedFilesystemShrinkError(f"{name} failed during staged filesystem shrink: {exc}") from exc

    loop_device: str | None = None
    primary_error: BaseException | None = None
    try:
        attached = invoke("losetup", [
            "--find", "--show", "--offset", str(offset),
            "--sizelimit", str(source_partition_bytes), staged.path,
        ], command_timeout=60)
        loop_device = (attached.stdout or "").strip()
        if not re.fullmatch(r"/dev/loop[0-9]+", loop_device):
            raise StagedFilesystemShrinkError("losetup returned an unexpected loop-device path")
        validator = block_device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
        try:
            if not validator(loop_device):
                raise StagedFilesystemShrinkError("created loop path is not a block device")
        except OSError as exc:
            raise StagedFilesystemShrinkError(f"cannot verify created loop device: {exc}") from exc

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
            raise StagedFilesystemShrinkError(f"loop backing mapping failed read-back validation: {exc}") from exc

        try:
            if safety_check is None:
                check_capture_source_safe(loop_device, runner=run, which=resolve)
            else:
                safety_check(loop_device)
        except (SourceSafetyError, OSError, subprocess.SubprocessError) as exc:
            raise StagedFilesystemShrinkError(f"loop partition must be offline and unused: {exc}") from exc

        detected = invoke("blkid", ["-p", "-s", "TYPE", "-o", "value", loop_device],
                          command_timeout=60).stdout.strip().lower()
        if detected not in {"ext2", "ext3", "ext4"}:
            raise StagedFilesystemShrinkError(
                f"staged shrink supports ext2/3/4 only; detected {detected or 'unknown'}"
            )
        invoke("e2fsck", ["-f", "-n", loop_device])
        header = invoke("dumpe2fs", ["-h", loop_device], command_timeout=60).stdout
        block_size_match = re.search(r"^Block size:\s*(\d+)\s*$", header, re.MULTILINE)
        block_count_match = re.search(r"^Block count:\s*(\d+)\s*$", header, re.MULTILINE)
        if not block_size_match or not block_count_match:
            raise StagedFilesystemShrinkError("dumpe2fs did not report block size and block count")
        block_size, old_blocks = int(block_size_match.group(1)), int(block_count_match.group(1))
        if (block_size < 1024 or block_size > 65536 or block_size & (block_size - 1)
                or old_blocks <= 0):
            raise StagedFilesystemShrinkError("staged ext filesystem geometry is invalid")
        if target_filesystem_size_bytes % block_size:
            raise StagedFilesystemShrinkError("filesystem target is not aligned to the ext block size")
        target_blocks = target_filesystem_size_bytes // block_size
        if target_blocks <= 0 or target_blocks >= old_blocks:
            raise StagedFilesystemShrinkError("filesystem target must be smaller than the current filesystem")
        invoke("resize2fs", [loop_device, str(target_blocks)])
        invoke("e2fsck", ["-f", "-n", loop_device])
        verified_header = invoke("dumpe2fs", ["-h", loop_device], command_timeout=60).stdout
        verified_match = re.search(r"^Block count:\s*(\d+)\s*$", verified_header, re.MULTILINE)
        if not verified_match or int(verified_match.group(1)) != target_blocks:
            raise StagedFilesystemShrinkError("filesystem block count failed post-shrink read-back")
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if loop_device is not None:
            try:
                invoke("losetup", ["--detach", loop_device], command_timeout=60)
            except BaseException as detach_exc:
                if primary_error is None:
                    raise StagedFilesystemShrinkError(
                        f"filesystem operation ended but loop device could not be detached: {detach_exc}"
                    ) from detach_exc
                # Preserve the original failure; the detach failure is still
                # surfaced in its message so operators know the loop may remain.
                primary_error.add_note(f"IMPORTANT: loop device {loop_device} could not be detached: {detach_exc}")

    try:
        output_digest = _digest_file(staged.path)
    except OSError as exc:
        raise StagedFilesystemShrinkError(f"cannot hash staged RAW after filesystem shrink: {exc}") from exc
    if output_digest == staged.sha256:
        raise StagedFilesystemShrinkError("filesystem shrink reported success but staged RAW bytes did not change")
    return StagedRawDiskImage(staged.path, staged.size_bytes, output_digest)
