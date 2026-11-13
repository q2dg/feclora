"""Read-only parsing of sfdisk GPT JSON for proportional-layout previews."""
from __future__ import annotations

import json
import re
from typing import Any


class GPTInspectionError(ValueError):
    """The source partition table cannot be trusted for a preview."""


_GUID = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)


def parse_sfdisk_gpt_json(
    output: str,
    *,
    disk_path: str,
    expected_sector_size: int,
) -> tuple[dict[str, object], ...]:
    """Parse sfdisk --json output into planner records; never executes writes."""
    if (
        not isinstance(disk_path, str)
        or not disk_path.startswith("/dev/")
        or "\x00" in disk_path
    ):
        raise GPTInspectionError("source disk must be an absolute /dev/ path")
    if (
        isinstance(expected_sector_size, bool)
        or not isinstance(expected_sector_size, int)
        or expected_sector_size not in {512, 4096}
    ):
        raise GPTInspectionError("logical sector size must be 512 or 4096 bytes")
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GPTInspectionError("sfdisk returned invalid JSON") from exc
    table = payload.get("partitiontable") if isinstance(payload, dict) else None
    if not isinstance(table, dict):
        raise GPTInspectionError("sfdisk JSON has no partitiontable object")
    if table.get("label") != "gpt":
        raise GPTInspectionError("only GPT source partition tables are supported")
    if table.get("unit") != "sectors":
        raise GPTInspectionError("sfdisk partition units must be sectors")
    sector_size = table.get("sectorsize")
    if (
        isinstance(sector_size, bool)
        or not isinstance(sector_size, int)
        or sector_size != expected_sector_size
    ):
        raise GPTInspectionError("sfdisk logical sector size does not match the inspected disk")
    partitions = table.get("partitions")
    if not isinstance(partitions, list) or not partitions:
        raise GPTInspectionError("GPT source has no readable partitions")

    result: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    previous_end = -1
    for index, item in enumerate(partitions):
        if not isinstance(item, dict):
            raise GPTInspectionError(f"partition entry {index} is invalid")
        node = item.get("node")
        start = item.get("start")
        size = item.get("size")
        type_guid = item.get("type")
        if not isinstance(node, str) or not node.startswith(disk_path) or "\x00" in node:
            raise GPTInspectionError(f"partition entry {index} does not belong to {disk_path}")
        if node == disk_path or node in seen_paths:
            raise GPTInspectionError(f"partition entry {index} has a duplicate or invalid node")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise GPTInspectionError(f"{node} has an invalid start sector")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise GPTInspectionError(f"{node} has an invalid size in sectors")
        if not isinstance(type_guid, str) or not _GUID.fullmatch(type_guid):
            raise GPTInspectionError(f"{node} has an invalid GPT type GUID")
        if start < previous_end:
            raise GPTInspectionError("GPT partitions overlap or are not in start-sector order")
        previous_end = start + size
        seen_paths.add(node)
        record: dict[str, object] = {
            "node": node,
            "start": start,
            "size": size,
            "type": type_guid,
        }
        for source_key, target_key in (("uuid", "uuid"), ("name", "name")):
            value = item.get(source_key)
            if value is not None:
                if not isinstance(value, str):
                    raise GPTInspectionError(f"{node} has invalid {source_key} metadata")
                record[target_key] = value
        if "uuid" in record and not _GUID.fullmatch(str(record["uuid"])):
            raise GPTInspectionError(f"{node} has an invalid partition UUID")
        result.append(record)
    return tuple(result)
