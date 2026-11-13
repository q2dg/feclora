"""Preview-only proportional GPT partition layout planning.

This module does not modify filesystems, partition tables, or block devices.
Callers must supply filesystem-native minimum byte sizes obtained by a
separate, trusted offline probe. Unknown minima fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


_FIXED_SIZE_FILESYSTEMS = frozenset({
    "btrfs", "exfat", "fat", "fat16", "fat32", "f2fs",
    "ntfs", "ntfs3", "swap", "vfat", "xfs",
})


class PartitionLayoutError(ValueError):
    """A proportional destination layout cannot be planned safely."""


@dataclass(frozen=True)
class PlannedPartition:
    node: str
    type_guid: str
    partuuid: str | None
    name: str | None
    start_sector: int
    size_sectors: int
    minimum_size_bytes: int

    @property
    def end_sector(self) -> int:
        return self.start_sector + self.size_sectors - 1


def _integer(value: object, field: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PartitionLayoutError(f"{field} must be an integer >= {minimum}")
    return value



def plan_proportional_gpt_layout(
    partitions: Sequence[Mapping[str, object]],
    *,
    source_size_bytes: int,
    target_size_bytes: int,
    sector_size: int,
    partition_table_type: str,
    minimum_sizes_bytes: Mapping[str, int],
    filesystem_types: Mapping[str, str],
) -> tuple[PlannedPartition, ...]:
    """Return a deterministic, aligned GPT layout or fail closed.

    All partitions must carry a unique /dev node and a GPT type GUID. The
    caller must provide a filesystem-native minimum size and detected type for every partition. Only ext2/3/4 and NTFS may be reduced; all other types must remain at their original byte size.
    The planner preserves every source partition start and identifier. It
    may shorten only the final ext2/3/4 partition to the target's last usable
    GPT LBA. It never relocates partitions or redistributes capacity.

    The returned plan is advisory only; it is not an authorization to write.
    """
    source_size = _integer(source_size_bytes, "source_size_bytes")
    target_size = _integer(target_size_bytes, "target_size_bytes")
    sector = _integer(sector_size, "sector_size")
    if partition_table_type != "gpt":
        raise PartitionLayoutError("only GPT partition tables are supported by proportional planning")
    if sector not in {512, 4096}:
        raise PartitionLayoutError("logical sector size must be 512 or 4096 bytes")
    if source_size % sector or target_size % sector:
        raise PartitionLayoutError("source and target sizes must be sector aligned")
    if target_size >= source_size:
        raise PartitionLayoutError("proportional shrink planning requires a smaller target")
    if not isinstance(partitions, Sequence) or isinstance(partitions, (str, bytes)) or not partitions:
        raise PartitionLayoutError("at least one GPT partition is required")
    if not isinstance(minimum_sizes_bytes, Mapping) or not isinstance(filesystem_types, Mapping):
        raise PartitionLayoutError("filesystem minimum-size and type maps are required")

    source_sectors = source_size // sector
    target_sectors = target_size // sector
    # GPT reserves LBAs 0..33 and the final 33 LBAs for headers/tables.
    first_usable = 34
    last_usable_exclusive = target_sectors - 33
    if last_usable_exclusive <= first_usable:
        raise PartitionLayoutError("target is too small for GPT metadata")

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    previous_end = first_usable
    for index, raw in enumerate(partitions):
        if not isinstance(raw, Mapping):
            raise PartitionLayoutError(f"partition {index} is not an object")
        node = raw.get("node")
        type_guid = raw.get("type")
        if not isinstance(node, str) or not node.startswith("/dev/") or "\x00" in node:
            raise PartitionLayoutError(f"partition {index} has an invalid device node")
        if node in seen:
            raise PartitionLayoutError(f"duplicate partition node: {node}")
        seen.add(node)
        if not isinstance(type_guid, str) or not re.fullmatch(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}", type_guid):
            raise PartitionLayoutError(f"partition {node} has no valid GPT type GUID")
        start = _integer(raw.get("start"), f"{node} start", minimum=0)
        size = _integer(raw.get("size"), f"{node} size")
        end = start + size
        if end > source_sectors - 33:
            raise PartitionLayoutError(f"partition {node} exceeds source GPT usable space")
        if start < previous_end:
            raise PartitionLayoutError("source partitions overlap or are not in start-sector order")
        previous_end = end
        minimum_bytes = _integer(minimum_sizes_bytes.get(node), f"{node} filesystem minimum")
        filesystem = filesystem_types.get(node)
        if not isinstance(filesystem, str) or not filesystem:
            raise PartitionLayoutError(f"{node} filesystem type is unknown")
        normalized_filesystem = filesystem.lower()
        if normalized_filesystem not in {"ext2", "ext3", "ext4"} | _FIXED_SIZE_FILESYSTEMS:
            raise PartitionLayoutError(
                f"{node} uses unsupported filesystem or storage layer {filesystem}"
            )
        if normalized_filesystem not in {"ext2", "ext3", "ext4", "ntfs", "ntfs3"} and minimum_bytes != size * sector:
            raise PartitionLayoutError(
                f"{node} uses {filesystem}; this planner only permits shrinking ext2/3/4 and NTFS"
            )
        minimum_sectors = (minimum_bytes + sector - 1) // sector
        if minimum_sectors > size:
            raise PartitionLayoutError(f"{node} filesystem minimum exceeds its source partition")
        normalized.append({
            "node": node,
            "type": type_guid,
            "uuid": raw.get("uuid") if isinstance(raw.get("uuid"), str) else None,
            "name": raw.get("name") if isinstance(raw.get("name"), str) else None,
            "source_size": size,
            "minimum_sectors": minimum_sectors,
            "minimum_bytes": minimum_bytes,
            "weight": max(0, size - minimum_sectors),
        })

    # Preserve every source partition start. Relocating a partition would
    # require a separate data-movement transaction and is deliberately not
    # inferred by this planner.
    result = []
    for index, item in enumerate(normalized):
        start = int(partitions[index]["start"])
        size_sectors = int(item["source_size"])
        end_exclusive = start + size_sectors
        if start < first_usable:
            raise PartitionLayoutError("source partition starts inside reserved GPT metadata")
        if start >= last_usable_exclusive:
            raise PartitionLayoutError("a source partition starts beyond the smaller target GPT boundary")
        if end_exclusive > last_usable_exclusive:
            if index != len(normalized) - 1:
                raise PartitionLayoutError(
                    "only the final source partition can be shortened without relocating later partitions"
                )
            filesystem = str(filesystem_types[str(item["node"])]).lower()
            if filesystem not in {"ext2", "ext3", "ext4", "ntfs", "ntfs3"}:
                raise PartitionLayoutError(
                    f"final partition uses {filesystem}; only ext2/3/4 and NTFS can be shortened"
                )
            size_sectors = last_usable_exclusive - start
            minimum = (int(item["minimum_bytes"]) + sector - 1) // sector
            if size_sectors < minimum:
                raise PartitionLayoutError(
                    "the final ext filesystem minimum does not fit at its original partition start"
                )
        result.append(PlannedPartition(
            node=str(item["node"]),
            type_guid=str(item["type"]),
            partuuid=item["uuid"] if isinstance(item["uuid"], str) else None,
            name=item["name"] if isinstance(item["name"], str) else None,
            start_sector=start,
            size_sectors=size_sectors,
            minimum_size_bytes=int(item["minimum_bytes"]),
        ))
    return tuple(result)
