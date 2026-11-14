"""Guarded destructive restore of a prepared proportional RAW staging image."""
from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable

from .disk_restore import DiskRestoreError, _target_geometry
from .gpt_binary import GPTBinaryError, inspect_gpt_binary
from .privilege import PrivilegeError, privileged_argv
from .process_control import stop_process
from .source_safety import SourceSafetyError, check_capture_source_safe
from .proportional_staging import StagedRawDiskImage


class StagedProportionalRestoreError(DiskRestoreError):
    """A proportional restore was rejected or could not be verified."""


def _hash_open_file(fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return total, digest.hexdigest()


def restore_staged_proportional_image(
    staged: StagedRawDiskImage,
    target_path: str,
    *,
    sector_size: int,
    confirmation: str,
    executables: dict[str, str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    device_identity: Callable[[str], Any] | None = None,
    runner: Callable[..., Any] | None = None,
    popen_factory: Callable[..., Any] | None = None,
    target_safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    pre_write_callback: Callable[[], None] | None = None,
) -> str:
    """Restore only to an exact-size whole disk and verify every written byte.

    The staged inode is opened with O_NOFOLLOW, locked and hashed before use.
    Device identity, geometry and safety are checked again immediately before
    dd. The destination is read back and SHA-256 compared before success.
    """
    if not isinstance(staged, StagedRawDiskImage):
        raise StagedProportionalRestoreError("a staged RAW image descriptor is required")
    if not isinstance(target_path, str) or not target_path.startswith("/dev/") or "\x00" in target_path:
        raise StagedProportionalRestoreError("target must be an absolute /dev/ path")
    if confirmation != f"ERASE {target_path}":
        raise StagedProportionalRestoreError(f"explicit confirmation required: ERASE {target_path}")
    if isinstance(sector_size, bool) or sector_size not in {512, 4096}:
        raise StagedProportionalRestoreError("logical sector size must be 512 or 4096 bytes")
    if (isinstance(staged.size_bytes, bool) or not isinstance(staged.size_bytes, int)
            or staged.size_bytes <= 0 or staged.size_bytes % sector_size
            or not isinstance(staged.sha256, str) or len(staged.sha256) != 64
            or any(c not in "0123456789abcdef" for c in staged.sha256)):
        raise StagedProportionalRestoreError("staged image size, sector alignment or SHA-256 is invalid")
    if not isinstance(staged.path, str) or not os.path.isabs(staged.path) or "\x00" in staged.path:
        raise StagedProportionalRestoreError("staged image path must be absolute")

    directory_fd = image_fd = -1
    write_process = read_process = None
    write_stderr = read_stderr = None
    try:
        directory_fd = os.open(
            os.path.dirname(staged.path),
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        parent = os.fstat(directory_fd)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077
                or parent.st_uid != os.geteuid()):
            raise StagedProportionalRestoreError("staging directory is not private and owned by this user")
        basename = os.path.basename(staged.path)
        path_info = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(path_info.st_mode) or path_info.st_mode & 0o077
                or path_info.st_nlink != 1 or path_info.st_size != staged.size_bytes
                or path_info.st_uid != os.geteuid()):
            raise StagedProportionalRestoreError("staged image is not a private single-link regular file")
        image_fd = os.open(
            basename, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd
        )
        opened = os.fstat(image_fd)
        current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != current.st_dev
                or opened.st_ino != current.st_ino or opened.st_nlink != 1
                or opened.st_uid != os.geteuid() or opened.st_mode & 0o077
                or opened.st_size != staged.size_bytes):
            raise StagedProportionalRestoreError("staged image identity changed while opening")
        fcntl.flock(image_fd, fcntl.LOCK_EX)
        actual_size, actual_digest = _hash_open_file(image_fd)
        if actual_size != staged.size_bytes or actual_digest != staged.sha256:
            raise StagedProportionalRestoreError("staged image size or SHA-256 changed before restore")
        try:
            with os.fdopen(os.dup(image_fd), "rb") as image:
                parsed = inspect_gpt_binary(
                    image, sector_size=sector_size, disk_size_bytes=staged.size_bytes
                )
            if not parsed.get("primary_backup_consistent"):
                raise StagedProportionalRestoreError("staged GPT copies are inconsistent")
        except GPTBinaryError as exc:
            raise StagedProportionalRestoreError(f"staged GPT validation failed: {exc}") from exc

        available = executables or {}
        dd = available.get("dd") or shutil.which("dd")
        lsblk = available.get("lsblk") or shutil.which("lsblk")
        if not dd or not lsblk:
            raise StagedProportionalRestoreError("dd and lsblk are required")
        run = runner or subprocess.run
        valid_device = device_validator or (lambda p: stat.S_ISBLK(os.stat(p).st_mode))
        identity = device_identity or (lambda p: os.stat(p).st_rdev)
        safety = target_safety_check or check_capture_source_safe

        def check_target():
            try:
                if not valid_device(target_path):
                    raise StagedProportionalRestoreError("target is not an accessible whole-disk block device")
                size, logical_sector = _target_geometry(target_path, lsblk, run)
                if size != staged.size_bytes:
                    raise StagedProportionalRestoreError(
                        "destination capacity must exactly equal the staged image size"
                    )
                if logical_sector != sector_size:
                    raise StagedProportionalRestoreError(
                        "destination logical sector size differs from the staged image"
                    )
                safety(target_path)
                return identity(target_path)
            except SourceSafetyError as exc:
                raise StagedProportionalRestoreError(f"unsafe destination: {exc}") from exc
            except OSError as exc:
                raise StagedProportionalRestoreError(f"cannot establish destination identity: {exc}") from exc

        initial_identity = check_target()
        if pre_write_callback is not None:
            pre_write_callback()
        if check_target() != initial_identity:
            raise StagedProportionalRestoreError("destination block-device identity changed before writing")

        factory = popen_factory or subprocess.Popen
        write_stderr = tempfile.TemporaryFile(mode="w+b")
        try:
            command = privileged_argv(
                [dd, f"if=/proc/self/fd/{image_fd}", f"of={target_path}",
                 "bs=4M", "conv=fsync", "status=none"],
                effective_uid=effective_uid,
            )
            write_process = factory(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=write_stderr, close_fds=True, pass_fds=(image_fd,),
            )
        except (OSError, PrivilegeError) as exc:
            raise StagedProportionalRestoreError(f"could not start destination write: {exc}") from exc
        write_code = write_process.wait()
        if write_code != 0:
            write_stderr.seek(0)
            detail = write_stderr.read(8192).decode("utf-8", errors="replace").strip()
            raise StagedProportionalRestoreError(
                "destination write failed; disk may be partially modified"
                + (f": {detail}" if detail else "")
            )
        stop_process(write_process)
        write_process = None

        if check_target() != initial_identity:
            raise StagedProportionalRestoreError(
                "destination identity changed after writing; read-back verification was not attempted"
            )
        read_stderr = tempfile.TemporaryFile(mode="w+b")
        try:
            verify_command = privileged_argv(
                [dd, f"if={target_path}", "bs=4M", "iflag=count_bytes",
                 f"count={staged.size_bytes}", "status=none"],
                effective_uid=effective_uid,
            )
            read_process = factory(
                verify_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=read_stderr, close_fds=True,
            )
            if read_process.stdout is None:
                raise StagedProportionalRestoreError("read-back process has no output stream")
            digest = hashlib.sha256()
            read_size = 0
            while True:
                chunk = read_process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                read_size += len(chunk)
                digest.update(chunk)
            read_process.stdout.close()
            read_code = read_process.wait()
            if (read_code != 0 or read_size != staged.size_bytes
                    or digest.hexdigest() != staged.sha256):
                raise StagedProportionalRestoreError(
                    "destination read-back verification failed; disk contains unverified data"
                )
        finally:
            stop_process(read_process)
            read_process = None
        return staged.sha256
    except StagedProportionalRestoreError:
        raise
    except (OSError, PrivilegeError, SourceSafetyError, subprocess.SubprocessError) as exc:
        raise StagedProportionalRestoreError(
            f"proportional restore failed; destination may be modified if writing began: {exc}"
        ) from exc
    finally:
        stop_process(write_process)
        stop_process(read_process)
        for stream in (write_stderr, read_stderr):
            if stream is not None:
                stream.close()
        if image_fd >= 0:
            os.close(image_fd)
        if directory_fd >= 0:
            os.close(directory_fd)
