"""Safe partition-range extraction and bounded block-to-block copying.

This module contains no device discovery or privilege escalation. Callers must
resolve devices, authorize destructive targets and run the storage safety
checks before opening descriptors. Offsets and lengths are byte-accurate.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from typing import Callable, Mapping


class PartitionRangeError(ValueError):
    """Partition metadata is malformed or outside the source image."""


@dataclass(frozen=True)
class PartitionRange:
    node: str
    start_sector: int
    sector_count: int
    sector_size: int
    offset_bytes: int
    length_bytes: int

    @property
    def end_bytes(self) -> int:
        return self.offset_bytes + self.length_bytes


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PartitionRangeError(f"{field} must be a positive integer")
    return value


def partition_ranges(
    table: Mapping[str, object],
    *,
    image_size_bytes: int,
    sector_size: int = 512,
) -> tuple[PartitionRange, ...]:
    """Parse sfdisk --json output and return bounded partition byte ranges."""
    image_size = _positive_int(image_size_bytes, "image_size_bytes")
    sector_size = _positive_int(sector_size, "sector_size")
    if image_size % sector_size:
        raise PartitionRangeError("image size is not a multiple of logical sector size")
    partition_table = table.get("partitiontable")
    if not isinstance(partition_table, Mapping):
        raise PartitionRangeError("missing partitiontable object")
    raw_parts = partition_table.get("partitions")
    if not isinstance(raw_parts, list):
        raise PartitionRangeError("partitiontable.partitions must be a list")
    result: list[PartitionRange] = []
    seen_nodes: set[str] = set()
    occupied: list[tuple[int, int, str]] = []
    for index, raw in enumerate(raw_parts):
        if not isinstance(raw, Mapping):
            raise PartitionRangeError(f"partition {index} is not an object")
        node = raw.get("node")
        if not isinstance(node, str) or not node.startswith("/dev/") or "\x00" in node:
            raise PartitionRangeError(f"partition {index} has an invalid node")
        if node in seen_nodes:
            raise PartitionRangeError(f"duplicate partition node: {node}")
        seen_nodes.add(node)
        start = raw.get("start")
        count = raw.get("size")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise PartitionRangeError(f"partition {node} has an invalid start sector")
        count = _positive_int(count, f"partition {node} size")
        offset = start * sector_size
        length = count * sector_size
        end = offset + length
        if end > image_size:
            raise PartitionRangeError(f"partition {node} extends beyond the source image")
        for previous_start, previous_end, previous_node in occupied:
            if offset < previous_end and previous_start < end:
                raise PartitionRangeError(f"partition ranges overlap: {previous_node} and {node}")
        occupied.append((offset, end, node))
        result.append(PartitionRange(node, start, count, sector_size, offset, length))
    return tuple(result)


def select_partition_range(
    table: Mapping[str, object],
    selector: str,
    *,
    image_size_bytes: int,
    sector_size: int = 512,
) -> PartitionRange:
    """Select exactly one partition by node, PARTUUID, or partition name."""
    if not isinstance(selector, str) or not selector or "\x00" in selector:
        raise PartitionRangeError("partition selector must be a non-empty string")
    ranges = partition_ranges(
        table, image_size_bytes=image_size_bytes, sector_size=sector_size
    )
    parts = table["partitiontable"]["partitions"]  # validated by partition_ranges
    matches = []
    for item, part in zip(ranges, parts):
        if selector in (item.node, part.get("uuid"), part.get("name")):
            matches.append(item)
    if len(matches) != 1:
        raise PartitionRangeError(
            "partition selector is ambiguous or does not identify exactly one partition"
        )
    return matches[0]


@dataclass(frozen=True)
class RangeCopyResult:
    bytes_copied: int
    sha256: str


def copy_fd_range(
    source_fd: int,
    target_fd: int,
    *,
    source_offset: int,
    length: int,
    chunk_size: int = 4 * 1024 * 1024,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> RangeCopyResult:
    """Copy an exact byte range between already-authorized open descriptors."""
    if isinstance(source_offset, bool) or not isinstance(source_offset, int) or source_offset < 0:
        raise PartitionRangeError("source_offset must be a non-negative integer")
    length = _positive_int(length, "length")
    chunk_size = _positive_int(chunk_size, "chunk_size")
    source_stat = os.fstat(source_fd)
    target_stat = os.fstat(target_fd)
    if stat.S_ISREG(source_stat.st_mode) and source_offset + length > source_stat.st_size:
        raise PartitionRangeError("requested source range exceeds source file")
    if target_stat.st_size and target_stat.st_size < length:
        raise PartitionRangeError("target file is smaller than requested partition range")
    digest = hashlib.sha256()
    copied = 0
    while copied < length:
        if cancel_check is not None and cancel_check():
            raise InterruptedError("partition range copy cancelled")
        amount = min(chunk_size, length - copied)
        data = os.pread(source_fd, amount, source_offset + copied)
        if not data:
            raise PartitionRangeError("unexpected end of source while copying partition range")
        view = memoryview(data)
        written = 0
        while written < len(view):
            if cancel_check is not None and cancel_check():
                raise InterruptedError("partition range copy cancelled")
            count = os.pwrite(target_fd, view[written:], copied + written)
            if count <= 0:
                raise OSError("target descriptor made no write progress")
            written += count
        digest.update(data)
        copied += len(data)
        if progress_callback is not None:
            progress_callback(copied, length)
    return RangeCopyResult(copied, digest.hexdigest())


def load_sfdisk_json(raw: str) -> Mapping[str, object]:
    """Decode sfdisk JSON while rejecting duplicate object keys."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PartitionRangeError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        parsed = json.loads(raw, object_pairs_hook=unique_pairs)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PartitionRangeError("invalid sfdisk JSON") from exc
    if not isinstance(parsed, Mapping):
        raise PartitionRangeError("sfdisk JSON root must be an object")
    return parsed
