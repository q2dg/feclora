"""Coordinate private filesystem shrink and verified staged GPT rewrite."""
from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .gpt_binary import GPTBinaryError, inspect_gpt_binary
from .proportional_staging import (
    ProportionalStagingError,
    StagedRawDiskImage,
    apply_gpt_rewrite_to_staged_image,
)
from .staged_filesystem_shrink import (
    StagedFilesystemShrinkError,
    shrink_staged_ext_filesystem,
)
from .staged_ntfs_shrink import (
    StagedNTFSShrinkError,
    shrink_staged_ntfs_filesystem,
)


class ProportionalStagedPreparationError(RuntimeError):
    """A proportional RAW staging image could not be prepared safely."""


def prepare_proportional_staged_image(
    staged: StagedRawDiskImage,
    *,
    target_size_bytes: int,
    sector_size: int,
    planned_partitions: Sequence[object],
    filesystem_types: Mapping[str, str],
    executables: dict[str, str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    block_device_validator: Callable[[str], bool] | None = None,
    safety_check: Callable[[str], None] | None = None,
    effective_uid: Callable[[], int] | None = None,
    timeout: int = 1800,
) -> StagedRawDiskImage:
    """Shrink the final supported filesystem if needed, then rewrite staged GPT.

    The input is a private verified RAW staging descriptor. Partition identity
    and source geometry are read from that staged image itself; no source
    block-device path is opened. At most one partition may be shortened, and
    it must be the final source partition. The resulting RAW remains a private
    file and is never written to a destination device by this function.
    """
    if not isinstance(staged, StagedRawDiskImage):
        raise ProportionalStagedPreparationError("a verified private staged RAW image is required")
    if not isinstance(staged.path, str) or not os.path.isabs(staged.path) or "\x00" in staged.path:
        raise ProportionalStagedPreparationError("staged RAW path is invalid")
    if (isinstance(target_size_bytes, bool) or not isinstance(target_size_bytes, int)
            or target_size_bytes <= 0 or target_size_bytes >= staged.size_bytes):
        raise ProportionalStagedPreparationError("target size must be smaller than the staged source")
    if (isinstance(sector_size, bool) or not isinstance(sector_size, int)
            or sector_size not in {512, 4096}):
        raise ProportionalStagedPreparationError("logical sector size must be 512 or 4096 bytes")
    if not isinstance(planned_partitions, Sequence) or isinstance(planned_partitions, (str, bytes)):
        raise ProportionalStagedPreparationError("a complete planned partition sequence is required")
    if not isinstance(filesystem_types, Mapping):
        raise ProportionalStagedPreparationError("filesystem type mapping is required")

    plans = tuple(planned_partitions)
    if not plans:
        raise ProportionalStagedPreparationError("at least one planned partition is required")
    try:
        with open(staged.path, "rb") as stream:
            source_gpt = inspect_gpt_binary(
                stream, sector_size=sector_size, disk_size_bytes=staged.size_bytes
            )
    except (OSError, GPTBinaryError) as exc:
        raise ProportionalStagedPreparationError(f"cannot inspect staged source GPT: {exc}") from exc
    if source_gpt.get("sector_size") != sector_size:
        raise ProportionalStagedPreparationError("staged GPT sector size differs from the requested geometry")

    source_parts = source_gpt.get("partitions")
    if not isinstance(source_parts, list) or len(source_parts) != len(plans):
        raise ProportionalStagedPreparationError("planned partition count differs from staged source GPT")
    source_by_guid = {
        part.get("unique_guid"): part for part in source_parts
        if isinstance(part, dict) and isinstance(part.get("unique_guid"), str)
    }
    if len(source_by_guid) != len(source_parts):
        raise ProportionalStagedPreparationError("staged source GPT has missing or duplicate partition GUIDs")

    shortened: list[tuple[object, dict[str, Any], int]] = []
    seen_guids: set[str] = set()
    for plan in plans:
        partuuid = getattr(plan, "partuuid", None)
        node = getattr(plan, "node", None)
        start = getattr(plan, "start_sector", None)
        size = getattr(plan, "size_sectors", None)
        type_guid = getattr(plan, "type_guid", None)
        if not isinstance(partuuid, str) or partuuid not in source_by_guid or partuuid in seen_guids:
            raise ProportionalStagedPreparationError("partition plan does not uniquely identify every source PARTUUID")
        seen_guids.add(partuuid)
        source_part = source_by_guid[partuuid]
        source_start = source_part.get("first_lba")
        source_end = source_part.get("last_lba")
        source_type = source_part.get("type_guid")
        if (isinstance(start, bool) or not isinstance(start, int) or start != source_start
                or isinstance(size, bool) or not isinstance(size, int) or size < 1
                or str(type_guid).lower() != str(source_type).lower()):
            raise ProportionalStagedPreparationError("partition plan changes source identity or start geometry")
        source_size = source_end - source_start + 1
        if size > source_size:
            raise ProportionalStagedPreparationError("partition plan cannot expand a source partition")
        if size < source_size:
            shortened.append((plan, source_part, source_size))

    if seen_guids != set(source_by_guid):
        raise ProportionalStagedPreparationError("partition plan does not cover every source GPT partition")
    if len(shortened) > 1:
        raise ProportionalStagedPreparationError("only one final source partition may be shortened")
    if shortened:
        plan, source_part, source_size_sectors = shortened[0]
        if plan is not plans[-1]:
            raise ProportionalStagedPreparationError("only the final source partition may be shortened")
        node = getattr(plan, "node", None)
        filesystem = filesystem_types.get(node) if isinstance(node, str) else None
        if not isinstance(filesystem, str):
            raise ProportionalStagedPreparationError("shortened partition filesystem type is unknown")
        filesystem = filesystem.lower()
        target_partition_bytes = plan.size_sectors * sector_size
        common = {
            "partition_start_sector": int(source_part["first_lba"]),
            "source_partition_size_sectors": source_size_sectors,
            "target_partition_size_bytes": target_partition_bytes,
            "sector_size": sector_size,
            "executables": executables,
            "runner": runner,
            "which": which,
            "block_device_validator": block_device_validator,
            "safety_check": safety_check,
            "effective_uid": effective_uid,
            "timeout": timeout,
        }
        try:
            if filesystem in {"ext2", "ext3", "ext4"}:
                # 64 KiB is divisible by every supported ext block size.
                filesystem_target = target_partition_bytes - (target_partition_bytes % 65536)
                if filesystem_target <= 0:
                    raise ProportionalStagedPreparationError("planned ext partition is too small")
                staged = shrink_staged_ext_filesystem(
                    staged,
                    target_filesystem_size_bytes=filesystem_target,
                    **common,
                )
            elif filesystem in {"ntfs", "ntfs3"}:
                staged = shrink_staged_ntfs_filesystem(
                    staged,
                    target_filesystem_size_bytes=target_partition_bytes,
                    **common,
                )
            else:
                raise ProportionalStagedPreparationError(
                    f"filesystem {filesystem} has no staged shrink executor"
                )
        except (StagedFilesystemShrinkError, StagedNTFSShrinkError) as exc:
            raise ProportionalStagedPreparationError(
                f"staged filesystem shrink failed; GPT was not rewritten: {exc}"
            ) from exc

    try:
        return apply_gpt_rewrite_to_staged_image(
            staged,
            target_size_bytes=target_size_bytes,
            sector_size=sector_size,
            planned_partitions=plans,
        )
    except (ProportionalStagingError, OSError, GPTBinaryError) as exc:
        raise ProportionalStagedPreparationError(
            f"staged GPT rewrite or read-back validation failed: {exc}"
        ) from exc
