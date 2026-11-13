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


def parse_sfdisk_gpt_disk_metadata(
    output: str, *, expected_sector_size: int, disk_size_bytes: int
) -> dict[str, object]:
    """Validate disk-level GPT identity and usable-LBA bounds from sfdisk JSON."""
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GPTInspectionError("sfdisk returned invalid JSON") from exc
    table = payload.get("partitiontable") if isinstance(payload, dict) else None
    if not isinstance(table, dict) or table.get("label") != "gpt":
        raise GPTInspectionError("sfdisk JSON has no GPT partitiontable object")
    disk_guid = table.get("id")
    if not isinstance(disk_guid, str) or not _GUID.fullmatch(disk_guid):
        raise GPTInspectionError("sfdisk did not report a valid GPT disk GUID")
    sector_size = table.get("sectorsize")
    first_lba = table.get("firstlba")
    last_lba = table.get("lastlba")
    if (isinstance(sector_size, bool) or sector_size != expected_sector_size
            or isinstance(first_lba, bool) or not isinstance(first_lba, int)
            or isinstance(last_lba, bool) or not isinstance(last_lba, int)
            or isinstance(disk_size_bytes, bool) or not isinstance(disk_size_bytes, int)
            or disk_size_bytes <= 0 or disk_size_bytes % expected_sector_size):
        raise GPTInspectionError("sfdisk GPT disk geometry is incomplete or invalid")
    disk_sectors = disk_size_bytes // expected_sector_size
    if first_lba < 34 or last_lba < first_lba or last_lba >= disk_sectors - 1:
        raise GPTInspectionError("sfdisk reported invalid GPT usable-LBA bounds")
    return {
        "disk_guid": disk_guid.lower(),
        "first_usable_lba": first_lba,
        "last_usable_lba": last_lba,
        "sector_size": sector_size,
    }


def parse_sfdisk_gpt_json(
    output: str,
    *,
    disk_path: str,
    expected_sector_size: int,
    disk_size_bytes: int | None = None,
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
    first_lba = table.get("firstlba")
    last_lba = table.get("lastlba")
    if disk_size_bytes is not None:
        if (isinstance(disk_size_bytes, bool) or not isinstance(disk_size_bytes, int)
                or disk_size_bytes <= 0 or disk_size_bytes % expected_sector_size):
            raise GPTInspectionError("source disk capacity is invalid for GPT bounds validation")
        disk_sectors = disk_size_bytes // expected_sector_size
        if (isinstance(first_lba, bool) or not isinstance(first_lba, int)
                or isinstance(last_lba, bool) or not isinstance(last_lba, int)):
            raise GPTInspectionError("sfdisk did not report GPT firstlba and lastlba bounds")
        if first_lba < 34 or last_lba < first_lba or last_lba >= disk_sectors - 1:
            raise GPTInspectionError("sfdisk reported invalid GPT usable-LBA bounds")
    elif first_lba is not None or last_lba is not None:
        if (isinstance(first_lba, bool) or not isinstance(first_lba, int)
                or isinstance(last_lba, bool) or not isinstance(last_lba, int)
                or first_lba < 34 or last_lba < first_lba):
            raise GPTInspectionError("sfdisk reported invalid GPT usable-LBA bounds")

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
        if (
            not isinstance(node, str)
            or not node.startswith(disk_path)
            or "\x00" in node
            or not re.fullmatch(r"(?:p?\d+|-part\d+)", node[len(disk_path):])
        ):
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
        if first_lba is not None and start < first_lba:
            raise GPTInspectionError(f"{node} starts before the GPT usable-LBA range")
        if last_lba is not None and start + size - 1 > last_lba:
            raise GPTInspectionError(f"{node} extends beyond the GPT usable-LBA range")
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
        attrs = item.get("attrs")
        if attrs is not None:
            if (not isinstance(attrs, str) or len(attrs) > 1024
                    or any(ord(character) < 32 or ord(character) == 127 for character in attrs)):
                raise GPTInspectionError(f"{node} has invalid GPT partition attributes")
            record["attrs"] = attrs
        result.append(record)
    return tuple(result)


def inspect_gpt_source(
    disk_path: str,
    *,
    runner=None,
    which=None,
    device_validator=None,
    safety_check=None,
    effective_uid=None,
) -> dict[str, object]:
    """Discover a whole-disk GPT source and filesystem types using read-only tools.

    The disk must be offline and unused. Returned partition records are suitable
    as planner input; no partition table or filesystem is modified.
    """
    import os
    import shutil
    import stat
    import subprocess

    from .privilege import PrivilegeError, privileged_argv
    from .source_safety import SourceSafetyError, check_capture_source_safe

    if not isinstance(disk_path, str) or not disk_path.startswith("/dev/") or "\\x00" in disk_path:
        raise GPTInspectionError("source disk must be an absolute /dev/ path")
    validator = device_validator or (lambda path: stat.S_ISBLK(os.stat(path).st_mode))
    try:
        if not validator(disk_path):
            raise GPTInspectionError("source path is not a block device")
    except OSError as exc:
        raise GPTInspectionError(f"cannot inspect source block device: {exc}") from exc

    run = runner or subprocess.run
    resolve = which or shutil.which
    required = {name: resolve(name) for name in ("lsblk", "sfdisk", "blockdev")}
    missing = [name for name, path in required.items() if not path]
    if missing:
        raise GPTInspectionError("required disk inspection tools are missing: " + ", ".join(missing))

    try:
        if safety_check is None:
            check_capture_source_safe(
                disk_path, runner=run, which=resolve, effective_uid=effective_uid
            )
        else:
            safety_check(disk_path)
    except SourceSafetyError as exc:
        raise GPTInspectionError(f"source disk must be offline and unused: {exc}") from exc
    except Exception as exc:
        raise GPTInspectionError(f"source safety check failed: {exc}") from exc

    uid = effective_uid or os.geteuid

    def invoke(tool: str, args: list[str]) -> str:
        try:
            argv = privileged_argv(
                [required[tool], *args], effective_uid=uid, which=resolve
            )
            result = run(
                argv, check=True, capture_output=True, text=True, timeout=30
            )
            return result.stdout
        except (OSError, subprocess.SubprocessError, PrivilegeError) as exc:
            raise GPTInspectionError(f"{tool} read-only inspection failed: {exc}") from exc

    try:
        inventory = json.loads(invoke(
            "lsblk",
            ["--json", "--bytes", "--tree", "--paths", "--output",
             "PATH,TYPE,FSTYPE,SIZE,LOG-SEC,PTTYPE", disk_path],
        ))
    except (TypeError, json.JSONDecodeError) as exc:
        raise GPTInspectionError("lsblk returned invalid disk inventory JSON") from exc
    roots = inventory.get("blockdevices") if isinstance(inventory, dict) else None
    if not isinstance(roots, list) or len(roots) != 1 or not isinstance(roots[0], dict):
        raise GPTInspectionError("lsblk did not resolve exactly one source disk")
    root = roots[0]
    if root.get("path") != disk_path or root.get("type") != "disk":
        raise GPTInspectionError("source must resolve to the selected whole disk")
    sector_size = root.get("log-sec")
    if isinstance(sector_size, bool) or not isinstance(sector_size, int) or sector_size not in {512, 4096}:
        raise GPTInspectionError("lsblk did not report a supported logical sector size")
    if root.get("pttype") != "gpt":
        raise GPTInspectionError("only GPT source partition tables are supported")

    size_text = invoke("blockdev", ["--getsize64", disk_path]).strip()
    sector_text = invoke("blockdev", ["--getss", disk_path]).strip()
    try:
        disk_size = int(size_text)
        blockdev_sector = int(sector_text)
    except (TypeError, ValueError) as exc:
        raise GPTInspectionError("blockdev returned invalid disk geometry") from exc
    lsblk_size = root.get("size")
    if (isinstance(lsblk_size, bool) or not isinstance(lsblk_size, int)
            or lsblk_size <= 0 or lsblk_size != disk_size
            or blockdev_sector != sector_size or disk_size <= 0
            or disk_size % sector_size):
        raise GPTInspectionError("blockdev and lsblk disk geometry disagree")

    sfdisk_json = invoke("sfdisk", ["--json", disk_path])
    disk_metadata = parse_sfdisk_gpt_disk_metadata(
        sfdisk_json, expected_sector_size=sector_size, disk_size_bytes=disk_size
    )
    raw_partitions = parse_sfdisk_gpt_json(
        sfdisk_json,
        disk_path=disk_path,
        expected_sector_size=sector_size,
        disk_size_bytes=disk_size,
    )
    children = root.get("children") or []
    if not isinstance(children, list):
        raise GPTInspectionError("lsblk returned invalid partition hierarchy")
    filesystem_types: dict[str, str] = {}
    child_paths: set[str] = set()
    for child in children:
        if not isinstance(child, dict):
            raise GPTInspectionError("lsblk returned invalid partition metadata")
        node = child.get("path")
        fstype = child.get("fstype")
        if child.get("type") != "part":
            raise GPTInspectionError("lsblk source-disk child is not a partition")
        if not isinstance(node, str) or node in child_paths:
            raise GPTInspectionError("lsblk returned duplicate or invalid partition paths")
        child_paths.add(node)
        if isinstance(fstype, str) and fstype.strip():
            filesystem_types[node] = fstype.strip().lower()
    sfdisk_paths = {str(partition["node"]) for partition in raw_partitions}
    if child_paths != sfdisk_paths:
        raise GPTInspectionError("lsblk and sfdisk disagree about the source partition set")
    return {
        "disk_path": disk_path,
        "source_size_bytes": disk_size,
        "sector_size": sector_size,
        "partition_table_type": "gpt",
        **disk_metadata,
        "partitions": raw_partitions,
        "filesystem_types": filesystem_types,
    }
