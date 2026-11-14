"""Bind an offline source disk to a staged GPT image and prepare a smaller target."""
from __future__ import annotations

import os
import stat
from collections.abc import Callable
from typing import Any

from .filesystem_probe import FilesystemProbeError, build_proportional_gpt_plan
from .gpt_binary import GPTBinaryError, inspect_gpt_binary
from .proportional_preparation import (
    ProportionalStagedPreparationError,
    prepare_proportional_staged_image,
)
from .proportional_staging import StagedRawDiskImage


class ProportionalRestoreWorkflowError(RuntimeError):
    """The source inventory cannot safely describe the staged image."""


def require_distinct_block_devices(
    source_path: str,
    target_path: str,
    *,
    source_major_minor: str | None = None,
    target_major_minor: str | None = None,
    stat_device: Callable[[str], Any] = os.stat,
) -> tuple[Any, Any]:
    """Return stable rdev identities and reject aliases of the same physical disk."""
    if (not isinstance(source_path, str) or not source_path.startswith("/dev/")
            or not isinstance(target_path, str) or not target_path.startswith("/dev/")):
        raise ProportionalRestoreWorkflowError("source and destination must be /dev block-device paths")
    try:
        source = stat_device(source_path)
        target = stat_device(target_path)
    except OSError as exc:
        raise ProportionalRestoreWorkflowError(f"cannot inspect source or destination identity: {exc}") from exc
    if not stat.S_ISBLK(source.st_mode) or not stat.S_ISBLK(target.st_mode):
        raise ProportionalRestoreWorkflowError("source and destination must both be block devices")
    if source.st_rdev == target.st_rdev:
        raise ProportionalRestoreWorkflowError("source and destination resolve to the same physical block device")
    actual_source = f"{os.major(source.st_rdev)}:{os.minor(source.st_rdev)}"
    actual_target = f"{os.major(target.st_rdev)}:{os.minor(target.st_rdev)}"
    if source_major_minor is not None and source_major_minor != actual_source:
        raise ProportionalRestoreWorkflowError("selected source no longer matches the storage inventory identity")
    if target_major_minor is not None and target_major_minor != actual_target:
        raise ProportionalRestoreWorkflowError("selected destination no longer matches the storage inventory identity")
    return source.st_rdev, target.st_rdev


def _walk(items):
    for item in items:
        yield item
        yield from _walk(item.get("children") or [])


def prepare_from_offline_source_disk(
    staged: StagedRawDiskImage,
    source_disk: dict[str, Any],
    *,
    target_size_bytes: int,
    sector_size: int,
    runner: Callable[..., Any] | None = None,
    executables: dict[str, str | None] | None = None,
    which: Callable[[str], str | None] | None = None,
    device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    plan_callback: Callable[[tuple[object, ...]], None] | None = None,
) -> StagedRawDiskImage:
    """Probe the selected offline source read-only, then shrink only its private copy.

    GPT partition GUIDs, type GUIDs and geometry are taken from the verified
    staged RAW. The selected physical source must have matching capacity,
    sector size and exactly the same partition identities. Filesystem minimum
    probes run read-only against that offline source; all shrink operations
    are subsequently performed against the private staging image.
    """
    if not isinstance(staged, StagedRawDiskImage):
        raise ProportionalRestoreWorkflowError("verified private staging is required")
    if not isinstance(source_disk, dict) or source_disk.get("type") != "disk":
        raise ProportionalRestoreWorkflowError("an inventoried whole source disk is required")
    source_path = source_disk.get("path")
    if not isinstance(source_path, str) or not source_path.startswith("/dev/"):
        raise ProportionalRestoreWorkflowError("source disk path is invalid")
    if source_path.startswith("/dev/mapper/"):
        raise ProportionalRestoreWorkflowError("source must be the original whole physical disk")
    if source_disk.get("size_bytes") != staged.size_bytes:
        raise ProportionalRestoreWorkflowError("selected source capacity differs from the staged image")
    if source_disk.get("logical_sector_size") != sector_size:
        raise ProportionalRestoreWorkflowError("selected source logical sector size differs from the staged image")
    if target_size_bytes >= staged.size_bytes:
        raise ProportionalRestoreWorkflowError("proportional restore requires a smaller destination")

    try:
        with open(staged.path, "rb") as stream:
            gpt = inspect_gpt_binary(
                stream, sector_size=sector_size, disk_size_bytes=staged.size_bytes
            )
    except (OSError, GPTBinaryError) as exc:
        raise ProportionalRestoreWorkflowError(f"cannot inspect staged source GPT: {exc}") from exc
    if not gpt.get("primary_backup_consistent"):
        raise ProportionalRestoreWorkflowError("staged GPT copies are inconsistent")
    partitions = gpt.get("partitions")
    if not isinstance(partitions, (list, tuple)) or not partitions:
        raise ProportionalRestoreWorkflowError("staged image has no GPT partitions")

    source_parts = [
        item for item in _walk(source_disk.get("children") or [])
        if item.get("type") == "part"
    ]
    by_partuuid: dict[str, dict[str, Any]] = {}
    for item in source_parts:
        partuuid = item.get("partuuid")
        if not isinstance(partuuid, str) or not partuuid:
            raise ProportionalRestoreWorkflowError("source inventory lacks GPT PARTUUID metadata")
        if partuuid in by_partuuid:
            raise ProportionalRestoreWorkflowError("source inventory contains duplicate PARTUUID values")
        by_partuuid[partuuid.lower()] = item

    plan_input = []
    filesystem_types: dict[str, str] = {}
    expected_guids = set()
    for partition in partitions:
        partuuid = partition.get("unique_guid")
        if not isinstance(partuuid, str):
            raise ProportionalRestoreWorkflowError("staged GPT partition has no unique GUID")
        key = partuuid.lower()
        if key in expected_guids:
            raise ProportionalRestoreWorkflowError("staged GPT has duplicate partition identities")
        expected_guids.add(key)
        source_part = by_partuuid.get(key)
        if source_part is None:
            raise ProportionalRestoreWorkflowError(
                f"selected source disk is missing staged partition PARTUUID {partuuid}"
            )
        node = source_part.get("path")
        filesystem = source_part.get("filesystem")
        if not isinstance(node, str) or not node.startswith("/dev/"):
            raise ProportionalRestoreWorkflowError("source partition path is invalid")
        if not isinstance(filesystem, str) or not filesystem:
            raise ProportionalRestoreWorkflowError(f"filesystem type is unknown for {node}")
        if str(source_part.get("partition_type_guid") or "").lower() != str(partition.get("type_guid") or "").lower():
            raise ProportionalRestoreWorkflowError(f"GPT type GUID differs for source partition {node}")
        start = int(partition["first_lba"])
        size = int(partition["last_lba"]) - start + 1
        source_start = source_part.get("start_sector")
        source_size = source_part.get("size_bytes")
        if (isinstance(source_start, bool) or not isinstance(source_start, int)
                or source_start != start or source_size != size * sector_size):
            raise ProportionalRestoreWorkflowError(
                f"source partition geometry differs from staged GPT for {node}"
            )
        plan_input.append({
            "node": node,
            "type": partition["type_guid"],
            "uuid": partuuid,
            "name": partition.get("name"),
            "start": start,
            "size": size,
            "attrs": str(partition.get("attributes", 0)),
        })
        filesystem_types[node] = filesystem.lower()

    if expected_guids != set(by_partuuid):
        raise ProportionalRestoreWorkflowError("selected source disk has extra or missing GPT partitions")

    try:
        plans = build_proportional_gpt_plan(
            plan_input,
            source_size_bytes=staged.size_bytes,
            target_size_bytes=target_size_bytes,
            sector_size=sector_size,
            partition_table_type="gpt",
            filesystem_types=filesystem_types,
            executables=executables,
            runner=runner,
            which=which,
            device_validator=device_validator,
            safety_check=safety_check,
            effective_uid=effective_uid,
            source_first_usable_lba=int(gpt["first_usable_lba"]),
            source_last_usable_lba=int(gpt["last_usable_lba"]),
        )
        if plan_callback is not None:
            plan_callback(tuple(plans))
        return prepare_proportional_staged_image(
            staged,
            target_size_bytes=target_size_bytes,
            sector_size=sector_size,
            planned_partitions=plans,
            filesystem_types=filesystem_types,
            executables=executables,
            runner=runner,
            which=which,
            block_device_validator=device_validator,
            safety_check=safety_check,
            effective_uid=effective_uid,
        )
    except (FilesystemProbeError, ProportionalStagedPreparationError) as exc:
        raise ProportionalRestoreWorkflowError(
            f"source probing or private staging preparation failed: {exc}"
        ) from exc
