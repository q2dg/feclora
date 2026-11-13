"""Read-only source/target comparison for proportional GPT restore previews."""
from __future__ import annotations

import os
import re
import stat
from typing import Any, Callable

from .filesystem_probe import build_proportional_gpt_plan
from .gpt_inspection import inspect_gpt_source
from .target_inspection import inspect_restore_target


class ProportionalRestoreError(ValueError):
    """The selected source and target cannot form a safe proportional preview."""


def _block_identity(path: str) -> tuple[int, int]:
    info = os.stat(path)
    if not stat.S_ISBLK(info.st_mode):
        raise ProportionalRestoreError("source and target must both be block devices")
    return os.major(info.st_rdev), os.minor(info.st_rdev)


def preview_proportional_gpt_restore(
    source_disk_path: str,
    target_disk_path: str,
    *,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    minimum_probe: Callable[..., int] | None = None,
    source_inspector: Callable[..., dict[str, object]] | None = None,
    target_inspector: Callable[..., dict[str, object]] | None = None,
    device_identity: Callable[[str], object] | None = None,
) -> dict[str, object]:
    """Inspect both disks, compare their geometry and build a no-write plan.

    The returned plan is advisory. Existing target partitions are reported as
    data that a future explicitly authorized restore would replace; this
    function never wipes, shrinks, repartitions, copies or authorizes writes.
    """
    if (not isinstance(source_disk_path, str) or not source_disk_path.startswith("/dev/")
            or not isinstance(target_disk_path, str) or not target_disk_path.startswith("/dev/")
            or "\x00" in source_disk_path or "\x00" in target_disk_path):
        raise ProportionalRestoreError("source and target must be absolute /dev/ paths")

    identity = device_identity or _block_identity
    try:
        source_identity = identity(source_disk_path)
        target_identity = identity(target_disk_path)
    except (OSError, ProportionalRestoreError) as exc:
        raise ProportionalRestoreError(f"cannot establish source/target device identity: {exc}") from exc
    if source_identity == target_identity:
        raise ProportionalRestoreError("source and target resolve to the same physical block device")

    common = {
        "runner": runner,
        "which": which,
        "device_validator": device_validator,
        "safety_check": safety_check,
        "effective_uid": effective_uid,
    }
    try:
        source = (source_inspector or inspect_gpt_source)(source_disk_path, **common)
        target = (target_inspector or inspect_restore_target)(target_disk_path, **common)
    except Exception as exc:
        raise ProportionalRestoreError(f"source or target inspection failed: {exc}") from exc

    source_size = source.get("source_size_bytes")
    target_size = target.get("target_size_bytes")
    source_sector = source.get("sector_size")
    target_sector = target.get("sector_size")
    if (isinstance(source_size, bool) or not isinstance(source_size, int) or source_size <= 0
            or isinstance(target_size, bool) or not isinstance(target_size, int) or target_size <= 0):
        raise ProportionalRestoreError("source or target capacity is unknown")
    if (isinstance(source_sector, bool) or not isinstance(source_sector, int)
            or isinstance(target_sector, bool) or not isinstance(target_sector, int)
            or source_sector not in {512, 4096} or target_sector not in {512, 4096}):
        raise ProportionalRestoreError("source or target logical sector size is unsupported")
    if source_sector != target_sector:
        raise ProportionalRestoreError("source and target logical sector sizes differ")
    if target_size >= source_size:
        raise ProportionalRestoreError("proportional restore preview requires a strictly smaller target")
    if source.get("partition_table_type") != "gpt":
        raise ProportionalRestoreError("source partition table is not GPT")
    disk_guid = source.get("disk_guid")
    first_usable_lba = source.get("first_usable_lba")
    last_usable_lba = source.get("last_usable_lba")
    if not isinstance(disk_guid, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        disk_guid,
    ):
        raise ProportionalRestoreError("source GPT disk GUID is missing or invalid")
    source_sectors = source_size // source_sector
    if (isinstance(first_usable_lba, bool) or not isinstance(first_usable_lba, int)
            or isinstance(last_usable_lba, bool) or not isinstance(last_usable_lba, int)
            or first_usable_lba < 34 or last_usable_lba < first_usable_lba
            or last_usable_lba >= source_sectors - 1):
        raise ProportionalRestoreError("source GPT usable-LBA bounds are missing or invalid")
    if target.get("write_authorized") is not False:
        raise ProportionalRestoreError("target inspector did not preserve the no-write guarantee")

    try:
        plan = build_proportional_gpt_plan(
            source.get("partitions"),
            source_size_bytes=source_size,
            target_size_bytes=target_size,
            sector_size=source_sector,
            partition_table_type="gpt",
            filesystem_types=source.get("filesystem_types"),
            runner=runner,
            which=which,
            device_validator=device_validator,
            safety_check=safety_check,
            effective_uid=effective_uid,
            minimum_probe=minimum_probe,
        )
    except Exception as exc:
        raise ProportionalRestoreError(f"cannot construct a safe proportional layout: {exc}") from exc

    return {
        "source_disk": source_disk_path,
        "target_disk": target_disk_path,
        "source_size_bytes": source_size,
        "target_size_bytes": target_size,
        "sector_size": source_sector,
        "partition_table_type": "gpt",
        "source_gpt_disk_guid": source.get("disk_guid"),
        "source_gpt_first_usable_lba": source.get("first_usable_lba"),
        "source_gpt_last_usable_lba": source.get("last_usable_lba"),
        "partitions": plan,
        "existing_target_partitions": target.get("existing_partitions", ()),
        "target_identity": {
            "model": target.get("model"),
            "serial": target.get("serial"),
            "wwn": target.get("wwn"),
        },
        "destructive_confirmation_required": True,
        "write_authorized": False,
    }
