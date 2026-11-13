"""Read-only minimum-size probing for offline ext2/3/4 filesystems."""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from typing import Any, Callable

from .privilege import PrivilegeError, privileged_argv
from .source_safety import SourceSafetyError, check_capture_source_safe


class FilesystemProbeError(RuntimeError):
    """A filesystem cannot be safely measured for proportional shrinking."""


def probe_ext_minimum_size(
    device_path: str,
    *,
    filesystem_type: str,
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
) -> int:
    """Return resize2fs's estimated minimum byte size without changing the FS.

    The source must be an offline block device. The function verifies its
    detected filesystem type, performs a no-write e2fsck check, reads the
    filesystem block size, asks resize2fs for its minimum block count, and
    bounds the result by the actual device capacity. This estimate is a
    planning input, not a guarantee that a later shrink will succeed.
    """
    if not isinstance(device_path, str) or not device_path.startswith("/dev/") or "\x00" in device_path:
        raise FilesystemProbeError("filesystem probe target must be an absolute /dev/ path")
    expected = filesystem_type.lower() if isinstance(filesystem_type, str) else ""
    if expected not in {"ext2", "ext3", "ext4"}:
        raise FilesystemProbeError("only ext2, ext3 and ext4 minimum-size probes are supported")

    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(device_path):
            raise FilesystemProbeError("filesystem probe target is not an accessible block device")
    except OSError as exc:
        raise FilesystemProbeError(f"cannot inspect filesystem probe target: {exc}") from exc

    run = runner or subprocess.run
    resolve = which or shutil.which
    available = executables or {}
    required = {
        "blkid": available.get("blkid") or resolve("blkid"),
        "e2fsck": available.get("e2fsck") or resolve("e2fsck"),
        "dumpe2fs": available.get("dumpe2fs") or resolve("dumpe2fs"),
        "resize2fs": available.get("resize2fs") or resolve("resize2fs"),
        "blockdev": available.get("blockdev") or resolve("blockdev"),
    }
    missing = [name for name, path in required.items() if not path]
    if missing:
        raise FilesystemProbeError("required filesystem probe tools are missing: " + ", ".join(missing))

    try:
        if safety_check is None:
            check_capture_source_safe(device_path, runner=run, which=resolve)
        else:
            safety_check(device_path)
    except SourceSafetyError as exc:
        raise FilesystemProbeError(f"filesystem must be offline and unused: {exc}") from exc

    uid = effective_uid or os.geteuid
    def invoke(name: str, args: list[str]) -> Any:
        try:
            argv = privileged_argv([required[name], *args], effective_uid=uid)
            return run(argv, check=True, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise FilesystemProbeError(f"{name} read-only probe failed: {exc}") from exc

    detected = invoke("blkid", ["-p", "-s", "TYPE", "-o", "value", device_path]).stdout.strip().lower()
    if detected != expected:
        raise FilesystemProbeError(
            f"filesystem type mismatch: expected {expected}, detected {detected or 'unknown'}"
        )

    # -n prevents e2fsck from writing repairs; any reported inconsistency fails closed.
    invoke("e2fsck", ["-f", "-n", device_path])
    header = invoke("dumpe2fs", ["-h", device_path]).stdout
    block_match = re.search(r"^Block size:\s*(\d+)\s*$", header, re.MULTILINE)
    if not block_match:
        raise FilesystemProbeError("dumpe2fs did not report a filesystem block size")
    block_size = int(block_match.group(1))
    if block_size < 1024 or block_size > 65536 or block_size & (block_size - 1):
        raise FilesystemProbeError("filesystem block size is invalid or unsupported")

    estimate = invoke("resize2fs", ["-P", device_path])
    estimate_text = (estimate.stdout or "") + "\n" + (estimate.stderr or "")
    minimum_match = re.search(
        r"Estimated minimum size of the filesystem:\s*(\d+)", estimate_text
    )
    if not minimum_match:
        raise FilesystemProbeError("resize2fs did not report an estimated minimum block count")
    minimum_blocks = int(minimum_match.group(1))
    if minimum_blocks <= 0:
        raise FilesystemProbeError("resize2fs returned an invalid minimum block count")
    minimum_bytes = minimum_blocks * block_size

    capacity_result = invoke("blockdev", ["--getsize64", device_path])
    try:
        capacity = int(capacity_result.stdout.strip())
    except (TypeError, ValueError) as exc:
        raise FilesystemProbeError("blockdev returned an invalid device capacity") from exc
    if capacity <= 0 or minimum_bytes > capacity:
        raise FilesystemProbeError("estimated filesystem minimum exceeds the partition capacity")
    return minimum_bytes
