"""Safe conversion of an offline physical block device into a QCOW2 disk.

This is a storage engine primitive. Callers must place the output in a private
staging directory and publish it through Feclora's repository transaction.
The source is never opened for writing.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


class P2VError(RuntimeError):
    """Physical-to-virtual conversion failed closed."""


def _run(argv: list[str], runner: Callable[..., Any]) -> Any:
    try:
        result = runner(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=24 * 60 * 60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise P2VError(f"could not execute {Path(argv[0]).name}: {exc}") from exc
    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise P2VError(
            f"{Path(argv[0]).name} failed" + (f": {detail[:512]}" if detail else "")
        )
    return result


def convert_block_device_to_qcow2(
    source_path: str,
    output_path: str | os.PathLike[str],
    *,
    qemu_img: str | None = None,
    blockdev: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
    stat_device: Callable[[str], os.stat_result] = os.stat,
    source_safety_check: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Convert one offline block device to a verified QCOW2 image.

    The caller owns repository staging/publication. Existing output files are
    never overwritten. Source size and device identity are checked before and
    after conversion; qemu-img check and info must both validate the result.
    """
    if (not isinstance(source_path, str) or not source_path.startswith("/dev/")
            or os.path.normpath(source_path) != source_path or ".." in Path(source_path).parts):
        raise P2VError("source must be a normalized /dev block-device path")
    source = Path(source_path)
    destination = Path(output_path)
    if destination.name in {"", ".", ".."} or destination.suffix.lower() != ".qcow2":
        raise P2VError("output must be a .qcow2 file")
    if not destination.is_absolute():
        raise P2VError("output path must be absolute")
    try:
        parent_info = os.lstat(destination.parent)
        if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
                or parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o077):
            raise P2VError("output directory must be a private directory owned by the Feclora worker")
        if os.path.lexists(destination):
            raise P2VError("refusing to overwrite an existing P2V output")
        source_info = stat_device(source_path)
    except OSError as exc:
        raise P2VError(f"cannot inspect P2V source or output: {exc}") from exc
    if not stat.S_ISBLK(source_info.st_mode):
        raise P2VError("P2V source must be a physical block device")
    source_identity = (source_info.st_rdev, source_info.st_ino)
    if source_safety_check is None:
        from feclora.storage.source_safety import check_capture_source_safe, SourceSafetyError
        try:
            check_capture_source_safe(source_path)
        except SourceSafetyError as exc:
            raise P2VError(f"P2V source is not safe to read: {exc}") from exc
    else:
        source_safety_check(source_path)

    qemu_img = qemu_img or shutil.which("qemu-img")
    blockdev = blockdev or shutil.which("blockdev")
    if not qemu_img or not blockdev:
        raise P2VError("qemu-img and blockdev are required for P2V conversion")
    size_result = _run([blockdev, "--getsize64", source_path], runner)
    try:
        source_size = int(size_result.stdout.strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise P2VError("blockdev returned an invalid source capacity") from exc
    if source_size <= 0:
        raise P2VError("P2V source has no readable capacity")

    fd, temporary_name = tempfile.mkstemp(prefix=".feclora-p2v-", suffix=".qcow2", dir=destination.parent)
    os.fchmod(fd, 0o600)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        _run([
            qemu_img, "convert", "-p", "-f", "raw", "-O", "qcow2",
            "-o", "preallocation=off", source_path, str(temporary),
        ], runner)
        _run([qemu_img, "check", "-f", "qcow2", str(temporary)], runner)
        info_result = _run([qemu_img, "info", "--output=json", str(temporary)], runner)
        try:
            info = json.loads(info_result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise P2VError("qemu-img returned invalid QCOW2 metadata") from exc
        if (not isinstance(info, dict) or info.get("format") != "qcow2"
                or isinstance(info.get("virtual-size"), bool)
                or info.get("virtual-size") != source_size):
            raise P2VError("QCOW2 virtual capacity does not match the physical source")
        output_info = os.lstat(temporary)
        if (not stat.S_ISREG(output_info.st_mode) or stat.S_ISLNK(output_info.st_mode)
                or output_info.st_uid != os.geteuid() or output_info.st_mode & 0o077
                or output_info.st_size <= 0):
            raise P2VError("qemu-img produced an unsafe or empty QCOW2 output")
        current_source = stat_device(source_path)
        if (not stat.S_ISBLK(current_source.st_mode)
                or (current_source.st_rdev, current_source.st_ino) != source_identity):
            raise P2VError("P2V source device identity changed during conversion")
        if source_safety_check is None:
            check_capture_source_safe(source_path)
        else:
            source_safety_check(source_path)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {
            "source": source_path,
            "output": str(destination),
            "format": "qcow2",
            "virtual_size_bytes": source_size,
            "file_size_bytes": output_info.st_size,
            "verified": True,
        }
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
