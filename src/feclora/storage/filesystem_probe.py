"""Read-only minimum-size probing for offline ext2/3/4 and NTFS filesystems."""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from typing import Any, Callable, Mapping, Sequence

from .partition_layout import PlannedPartition, plan_proportional_gpt_layout

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



def probe_ntfs_minimum_size(
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
    """Return ntfsresize's read-only minimum-size estimate in bytes.

    NTFS must be offline and clean enough for ntfsresize's information probe.
    The estimate is advisory; the actual staged shrink must be revalidated.
    """
    if not isinstance(device_path, str) or not device_path.startswith("/dev/") or "\x00" in device_path:
        raise FilesystemProbeError("filesystem probe target must be an absolute /dev/ path")
    expected = filesystem_type.lower() if isinstance(filesystem_type, str) else ""
    if expected not in {"ntfs", "ntfs3"}:
        raise FilesystemProbeError("only NTFS minimum-size probes are supported")

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
        "ntfsresize": available.get("ntfsresize") or resolve("ntfsresize"),
        "blockdev": available.get("blockdev") or resolve("blockdev"),
    }
    missing = [name for name, executable in required.items() if not executable]
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
            return run(argv, check=True, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise FilesystemProbeError(f"{name} read-only probe failed: {exc}") from exc

    detected = invoke("blkid", ["-p", "-s", "TYPE", "-o", "value", device_path]).stdout.strip().lower()
    if detected not in {"ntfs", "ntfs3"}:
        raise FilesystemProbeError(
            f"filesystem type mismatch: expected NTFS, detected {detected or 'unknown'}"
        )

    # ntfsresize --info opens the filesystem read-only and never changes it.
    result = invoke("ntfsresize", ["--info", device_path])
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    matches = re.findall(r"You might resize at\s+([\d,]+)\s+bytes", output, re.IGNORECASE)
    if len(matches) != 1:
        raise FilesystemProbeError("ntfsresize did not report one unambiguous minimum size")
    minimum_bytes = int(matches[0].replace(",", ""))
    if minimum_bytes <= 0:
        raise FilesystemProbeError("ntfsresize returned an invalid minimum size")

    capacity_result = invoke("blockdev", ["--getsize64", device_path])
    try:
        capacity = int(capacity_result.stdout.strip())
    except (TypeError, ValueError) as exc:
        raise FilesystemProbeError("blockdev returned an invalid device capacity") from exc
    if capacity <= 0 or minimum_bytes > capacity:
        raise FilesystemProbeError("estimated filesystem minimum exceeds the partition capacity")
    return minimum_bytes


def build_proportional_gpt_plan(
    partitions: Sequence[Mapping[str, object]],
    *,
    source_size_bytes: int,
    target_size_bytes: int,
    sector_size: int,
    partition_table_type: str,
    filesystem_types: Mapping[str, str],
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    minimum_probe: Callable[..., int] | None = None,
    ntfs_minimum_probe: Callable[..., int] | None = None,
) -> tuple[PlannedPartition, ...]:
    """Build a GPT preview using live, read-only probes for shrinkable filesystems.

    Filesystems without a native, verified shrink probe remain fixed at their original byte size. Unknown
    filesystem types, missing signatures, probe failures and unsupported
    partition metadata fail closed. This function never writes to a device.
    """
    if not isinstance(partitions, Sequence) or isinstance(partitions, (str, bytes)) or not partitions:
        raise FilesystemProbeError("at least one partition is required for proportional planning")
    if not isinstance(filesystem_types, Mapping):
        raise FilesystemProbeError("filesystem type inventory is required")

    if isinstance(sector_size, bool) or not isinstance(sector_size, int) or sector_size not in {512, 4096}:
        raise FilesystemProbeError("logical sector size must be 512 or 4096 bytes")
    probe = minimum_probe or probe_ext_minimum_size
    ntfs_probe = ntfs_minimum_probe or probe_ntfs_minimum_size
    minimums: dict[str, int] = {}
    for index, partition in enumerate(partitions):
        if not isinstance(partition, Mapping):
            raise FilesystemProbeError(f"partition {index} metadata is invalid")
        node = partition.get("node")
        size_sectors = partition.get("size")
        if not isinstance(node, str) or not node.startswith("/dev/"):
            raise FilesystemProbeError(f"partition {index} has an invalid device node")
        if isinstance(size_sectors, bool) or not isinstance(size_sectors, int) or size_sectors <= 0:
            raise FilesystemProbeError(f"{node} has an invalid partition size")
        filesystem = filesystem_types.get(node)
        if not isinstance(filesystem, str) or not filesystem.strip():
            raise FilesystemProbeError(f"{node} filesystem type is unknown")
        filesystem = filesystem.lower()
        original_bytes = size_sectors * sector_size
        if filesystem in {"ext2", "ext3", "ext4"}:
            try:
                minimums[node] = probe(
                    node,
                    filesystem_type=filesystem,
                    executables=executables,
                    runner=runner,
                    which=which,
                    device_validator=device_validator,
                    safety_check=safety_check,
                    effective_uid=effective_uid,
                )
            except FilesystemProbeError:
                raise
            except Exception as exc:
                raise FilesystemProbeError(f"cannot determine minimum size for {node}: {exc}") from exc
        elif filesystem in {"ntfs", "ntfs3"}:
            try:
                minimums[node] = ntfs_probe(
                    node, filesystem_type=filesystem, executables=executables,
                    runner=runner, which=which, device_validator=device_validator,
                    safety_check=safety_check, effective_uid=effective_uid,
                )
            except FilesystemProbeError:
                raise
            except Exception as exc:
                raise FilesystemProbeError(f"cannot determine NTFS minimum size for {node}: {exc}") from exc
        else:
            # No shrink support is assumed for any other filesystem/container.
            minimums[node] = original_bytes

    try:
        return plan_proportional_gpt_layout(
            partitions,
            source_size_bytes=source_size_bytes,
            target_size_bytes=target_size_bytes,
            sector_size=sector_size,
            partition_table_type=partition_table_type,
            minimum_sizes_bytes=minimums,
            filesystem_types=filesystem_types,
        )
    except (TypeError, ValueError) as exc:
        raise FilesystemProbeError(f"proportional GPT layout is unsafe: {exc}") from exc


def preview_proportional_gpt_plan_from_disk(
    source_disk_path: str,
    *,
    target_size_bytes: int,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    minimum_probe: Callable[..., int] | None = None,
    ntfs_minimum_probe: Callable[..., int] | None = None,
) -> dict[str, object]:
    """Discover an offline GPT source and return a read-only smaller-target plan.

    This is a preview API only. It does not inspect or authorize the destination
    device, shrink filesystems, write GPT metadata, copy data, or verify a
    completed restore.
    """
    from .gpt_inspection import GPTInspectionError, inspect_gpt_source

    try:
        source = inspect_gpt_source(
            source_disk_path,
            runner=runner,
            which=which,
            device_validator=device_validator,
            safety_check=safety_check,
            effective_uid=effective_uid,
        )
    except GPTInspectionError as exc:
        raise FilesystemProbeError(f"cannot inspect proportional source disk: {exc}") from exc
    try:
        plan = build_proportional_gpt_plan(
            source["partitions"],
            source_size_bytes=int(source["source_size_bytes"]),
            target_size_bytes=target_size_bytes,
            sector_size=int(source["sector_size"]),
            partition_table_type=str(source["partition_table_type"]),
            filesystem_types=source["filesystem_types"],
            runner=runner,
            which=which,
            device_validator=device_validator,
            safety_check=safety_check,
            effective_uid=effective_uid,
            minimum_probe=minimum_probe,
            ntfs_minimum_probe=ntfs_minimum_probe,
        )
    except (FilesystemProbeError, TypeError, ValueError) as exc:
        raise FilesystemProbeError(f"cannot create proportional GPT preview: {exc}") from exc
    return {
        "source_disk": source_disk_path,
        "source_size_bytes": source["source_size_bytes"],
        "target_size_bytes": target_size_bytes,
        "sector_size": source["sector_size"],
        "partition_table_type": source["partition_table_type"],
        "partitions": plan,
        "write_authorized": False,
    }
