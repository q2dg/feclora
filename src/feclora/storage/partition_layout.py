"""Preview-only proportional GPT partition layout planning.

This module does not modify filesystems, partition tables, or block devices.
Callers must supply filesystem-native minimum byte sizes obtained by a
separate, trusted offline probe. Unknown minima fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


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


def _align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def plan_proportional_gpt_layout(
    partitions: Sequence[Mapping[str, object]],
    *,
    source_size_bytes: int,
    target_size_bytes: int,
    sector_size: int,
    minimum_sizes_bytes: Mapping[str, int],
    alignment_bytes: int = 1024 * 1024,
) -> tuple[PlannedPartition, ...]:
    """Return a deterministic, aligned GPT layout or fail closed.

    All partitions must carry a unique /dev node and a GPT type GUID. The
    caller must provide a filesystem-native minimum size for every partition.
    The planner preserves partition order and identifiers, packs partitions
    from the first usable GPT LBA, and distributes remaining capacity in
    proportion to each partition's shrinkable source size.

    The returned plan is advisory only; it is not an authorization to write.
    """
    source_size = _integer(source_size_bytes, "source_size_bytes")
    target_size = _integer(target_size_bytes, "target_size_bytes")
    sector = _integer(sector_size, "sector_size")
    alignment = _integer(alignment_bytes, "alignment_bytes")
    if sector not in {512, 4096}:
        raise PartitionLayoutError("logical sector size must be 512 or 4096 bytes")
    if alignment % sector:
        raise PartitionLayoutError("alignment must be a multiple of logical sector size")
    if source_size % sector or target_size % sector:
        raise PartitionLayoutError("source and target sizes must be sector aligned")
    if target_size >= source_size:
        raise PartitionLayoutError("proportional shrink planning requires a smaller target")
    if not isinstance(partitions, Sequence) or isinstance(partitions, (str, bytes)) or not partitions:
        raise PartitionLayoutError("at least one GPT partition is required")
    if not isinstance(minimum_sizes_bytes, Mapping):
        raise PartitionLayoutError("filesystem minimum-size map is required")

    source_sectors = source_size // sector
    target_sectors = target_size // sector
    alignment_sectors = alignment // sector
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
        if not isinstance(type_guid, str) or not type_guid.strip():
            raise PartitionLayoutError(f"partition {node} has no GPT type GUID")
        start = _integer(raw.get("start"), f"{node} start", minimum=0)
        size = _integer(raw.get("size"), f"{node} size")
        end = start + size
        if end > source_sectors - 33:
            raise PartitionLayoutError(f"partition {node} exceeds source GPT usable space")
        if start < previous_end:
            raise PartitionLayoutError("source partitions overlap or are not in start-sector order")
        previous_end = end
        minimum_bytes = _integer(minimum_sizes_bytes.get(node), f"{node} filesystem minimum")
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
            "weight": max(0, size - minimum_sectors),
        })

    cursor = first_usable
    starts: list[int] = []
    for _ in normalized:
        cursor = _align_up(cursor, alignment_sectors)
        starts.append(cursor)
        cursor += 1
    gaps = sum(starts[i] - (first_usable if i == 0 else starts[i - 1] + 1)
               for i in range(len(starts)))
    usable_partition_sectors = last_usable_exclusive - first_usable - gaps
    minima = [int(item["minimum_sectors"]) for item in normalized]
    minimum_total = sum(minima)
    if minimum_total > usable_partition_sectors:
        raise PartitionLayoutError("filesystem minimum sizes do not fit on the smaller target")

    extra = usable_partition_sectors - minimum_total
    weights = [int(item["weight"]) for item in normalized]
    if not any(weights):
        weights = [int(item["source_size"]) for item in normalized]
    weight_total = sum(weights)
    allocations = [(extra * weight) // weight_total for weight in weights]
    remainder = extra - sum(allocations)
    for index in range(remainder):
        allocations[index % len(allocations)] += 1
    sizes = [minimum + allocation for minimum, allocation in zip(minima, allocations)]

    result = []
    for item, start, size, minimum in zip(normalized, starts, sizes, minima):
        if start + size > last_usable_exclusive:
            raise PartitionLayoutError("planned partition extends into backup GPT metadata")
        result.append(PlannedPartition(
            node=str(item["node"]),
            type_guid=str(item["type"]),
            partuuid=item["uuid"] if isinstance(item["uuid"], str) else None,
            name=item["name"] if isinstance(item["name"], str) else None,
            start_sector=start,
            size_sectors=size,
            minimum_size_bytes=minimum * sector,
        ))
    return tuple(result)
