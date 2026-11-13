"""Independent, read-only validation of on-disk GPT structures.

The parser accepts a seekable binary stream and never writes to it. It checks
both GPT headers, their CRCs, both partition-entry arrays, and their agreement.
"""
from __future__ import annotations

import binascii
import struct
import uuid
from typing import BinaryIO


class GPTBinaryError(ValueError):
    """The binary GPT structures are malformed or inconsistent."""


_SIGNATURE = b"EFI PART"
_HEADER = struct.Struct("<8sIIIIQQQQ16sQIII")
_ENTRY_PREFIX = struct.Struct("<16s16sQQQ")
_MAX_ENTRY_ARRAY_BYTES = 64 * 1024 * 1024


def _read_at(stream: BinaryIO, offset: int, length: int) -> bytes:
    try:
        stream.seek(offset)
        data = stream.read(length)
    except (OSError, ValueError) as exc:
        raise GPTBinaryError(f"cannot read GPT data at byte offset {offset}: {exc}") from exc
    if not isinstance(data, bytes) or len(data) != length:
        raise GPTBinaryError(f"truncated GPT data at byte offset {offset}")
    return data


def _crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def _header(stream: BinaryIO, *, lba: int, sector_size: int, disk_sectors: int) -> dict[str, object]:
    raw_sector = _read_at(stream, lba * sector_size, sector_size)
    if len(raw_sector) < _HEADER.size:
        raise GPTBinaryError("logical sector is too small for a GPT header")
    fields = _HEADER.unpack_from(raw_sector)
    (signature, revision, header_size, stored_crc, reserved, current_lba,
     backup_lba, first_usable, last_usable, disk_guid_raw, entries_lba,
     entry_count, entry_size, entries_crc) = fields
    if signature != _SIGNATURE:
        raise GPTBinaryError(f"GPT signature is missing at LBA {lba}")
    if revision < 0x00010000 or header_size < _HEADER.size or header_size > sector_size:
        raise GPTBinaryError("GPT header revision or size is unsupported")
    if reserved != 0:
        raise GPTBinaryError("GPT header reserved field is nonzero")
    header_bytes = bytearray(raw_sector[:header_size])
    struct.pack_into("<I", header_bytes, 16, 0)
    if _crc32(bytes(header_bytes)) != stored_crc:
        raise GPTBinaryError(f"GPT header CRC mismatch at LBA {lba}")
    if current_lba != lba or backup_lba >= disk_sectors or backup_lba == current_lba:
        raise GPTBinaryError(f"GPT header LBA pointers are invalid at LBA {lba}")
    if first_usable < 2 or last_usable < first_usable or last_usable >= disk_sectors - 1:
        raise GPTBinaryError("GPT usable-LBA bounds exceed disk capacity")
    if entry_count < 1 or entry_size < 128 or entry_size % 8:
        raise GPTBinaryError("GPT partition-entry dimensions are invalid")
    array_bytes = entry_count * entry_size
    if array_bytes > _MAX_ENTRY_ARRAY_BYTES:
        raise GPTBinaryError("GPT partition-entry array exceeds the parser safety limit")
    array_sectors = (array_bytes + sector_size - 1) // sector_size
    if entries_lba < 2 or entries_lba + array_sectors > disk_sectors:
        raise GPTBinaryError("GPT partition-entry array lies outside disk capacity")
    if disk_guid_raw == bytes(16):
        raise GPTBinaryError("GPT disk GUID is zero")
    return {
        "revision": revision,
        "header_size": header_size,
        "current_lba": current_lba,
        "backup_lba": backup_lba,
        "first_usable_lba": first_usable,
        "last_usable_lba": last_usable,
        "disk_guid": str(uuid.UUID(bytes_le=disk_guid_raw)),
        "entries_lba": entries_lba,
        "entry_count": entry_count,
        "entry_size": entry_size,
        "entries_crc32": entries_crc,
        "array_bytes": array_bytes,
        "array_sectors": array_sectors,
    }


def _entries(raw: bytes, *, header: dict[str, object]) -> tuple[dict[str, object], ...]:
    if _crc32(raw) != header["entries_crc32"]:
        raise GPTBinaryError("GPT partition-entry array CRC mismatch")
    count = int(header["entry_count"])
    size = int(header["entry_size"])
    first_usable = int(header["first_usable_lba"])
    last_usable = int(header["last_usable_lba"])
    result = []
    seen_guids: set[str] = set()
    previous_end = first_usable - 1
    for index in range(count):
        entry = raw[index * size:(index + 1) * size]
        type_raw, unique_raw, first_lba, last_lba, attributes = _ENTRY_PREFIX.unpack_from(entry)
        if type_raw == bytes(16):
            if any(entry[16:]):
                raise GPTBinaryError(f"unused GPT entry {index + 1} contains nonzero fields")
            continue
        if unique_raw == bytes(16):
            raise GPTBinaryError(f"GPT entry {index + 1} has a zero unique GUID")
        type_guid = str(uuid.UUID(bytes_le=type_raw))
        unique_guid = str(uuid.UUID(bytes_le=unique_raw))
        if unique_guid in seen_guids:
            raise GPTBinaryError("GPT partition unique GUIDs are not unique")
        seen_guids.add(unique_guid)
        if first_lba < first_usable or last_lba < first_lba or last_lba > last_usable:
            raise GPTBinaryError(f"GPT partition {index + 1} lies outside usable LBAs")
        if first_lba <= previous_end:
            raise GPTBinaryError("GPT partitions overlap or are not ordered by starting LBA")
        previous_end = last_lba
        name_bytes = entry[56:128]
        try:
            name = name_bytes.decode("utf-16le", errors="strict").split("\x00", 1)[0]
        except UnicodeDecodeError as exc:
            raise GPTBinaryError(f"GPT partition {index + 1} has an invalid UTF-16 name") from exc
        result.append({
            "number": index + 1,
            "type_guid": type_guid,
            "unique_guid": unique_guid,
            "first_lba": first_lba,
            "last_lba": last_lba,
            "attributes": attributes,
            "name": name,
        })
    return tuple(result)


def inspect_gpt_binary(
    stream: BinaryIO, *, sector_size: int, disk_size_bytes: int
) -> dict[str, object]:
    """Validate primary/backup GPT copies and return their common metadata.

    The protective MBR must contain exactly one non-empty EE partition entry.
    Hybrid MBRs are rejected rather than interpreted ambiguously.
    """
    if isinstance(sector_size, bool) or sector_size not in {512, 4096}:
        raise GPTBinaryError("logical sector size must be 512 or 4096 bytes")
    if (isinstance(disk_size_bytes, bool) or not isinstance(disk_size_bytes, int)
            or disk_size_bytes <= 0 or disk_size_bytes % sector_size):
        raise GPTBinaryError("disk size must be a positive sector-aligned integer")
    disk_sectors = disk_size_bytes // sector_size
    if disk_sectors < 6:
        raise GPTBinaryError("disk is too small to contain GPT metadata")
    mbr = _read_at(stream, 0, 512)
    if mbr[510:512] != b"\x55\xaa":
        raise GPTBinaryError("protective MBR signature is missing")
    mbr_entries = [mbr[446 + i * 16:446 + (i + 1) * 16] for i in range(4)]
    populated = [entry for entry in mbr_entries if entry[4] != 0]
    if len(populated) != 1 or populated[0][4] != 0xEE:
        raise GPTBinaryError("MBR is not a single-entry protective MBR")
    protective = populated[0]
    if (protective[0] != 0
            or struct.unpack_from("<I", protective, 8)[0] != 1
            or struct.unpack_from("<I", protective, 12)[0] != min(disk_sectors - 1, 0xFFFFFFFF)):
        raise GPTBinaryError("protective MBR entry has invalid boot flag, start LBA or size")

    primary = _header(stream, lba=1, sector_size=sector_size, disk_sectors=disk_sectors)
    backup = _header(stream, lba=disk_sectors - 1, sector_size=sector_size,
                     disk_sectors=disk_sectors)
    for key in ("revision", "header_size", "disk_guid", "first_usable_lba",
                "last_usable_lba", "entry_count", "entry_size", "entries_crc32"):
        if primary[key] != backup[key]:
            raise GPTBinaryError(f"primary and backup GPT disagree on {key}")
    if primary["backup_lba"] != backup["current_lba"] or backup["backup_lba"] != primary["current_lba"]:
        raise GPTBinaryError("primary and backup GPT header pointers do not cross-reference")
    if primary["entries_lba"] + primary["array_sectors"] > primary["first_usable_lba"]:
        raise GPTBinaryError("primary GPT entry array overlaps usable partition space")
    if backup["entries_lba"] <= backup["last_usable_lba"]:
        raise GPTBinaryError("backup GPT entry array overlaps usable partition space")
    if backup["entries_lba"] + backup["array_sectors"] > backup["current_lba"]:
        raise GPTBinaryError("backup GPT entry array overlaps its header")

    array_length = int(primary["array_bytes"])
    primary_array = _read_at(stream, int(primary["entries_lba"]) * sector_size, array_length)
    backup_array = _read_at(stream, int(backup["entries_lba"]) * sector_size, array_length)
    if primary_array != backup_array:
        raise GPTBinaryError("primary and backup GPT partition-entry arrays differ")
    partitions = _entries(primary_array, header=primary)
    return {
        "disk_guid": primary["disk_guid"],
        "sector_size": sector_size,
        "disk_size_bytes": disk_size_bytes,
        "first_usable_lba": primary["first_usable_lba"],
        "last_usable_lba": primary["last_usable_lba"],
        "entry_count": primary["entry_count"],
        "entry_size": primary["entry_size"],
        "primary_entries_lba": primary["entries_lba"],
        "backup_entries_lba": backup["entries_lba"],
        "partitions": partitions,
        "protective_mbr": True,
        "primary_backup_consistent": True,
    }



def build_gpt_rewrite(
    source_stream: BinaryIO,
    *,
    source_size_bytes: int,
    target_size_bytes: int,
    sector_size: int,
    planned_partitions: tuple[object, ...],
) -> tuple[tuple[int, bytes], ...]:
    """Build sector-aligned GPT metadata patches for a smaller staging image.

    The function is pure with respect to both streams: it reads the validated
    source and returns byte patches; it never writes to either source or target.
    Partition slots, GUIDs, names, type GUIDs and attribute bits are retained.
    Only partition end LBAs and target-dependent GPT geometry/CRCs change.
    """
    source = inspect_gpt_binary(
        source_stream, sector_size=sector_size, disk_size_bytes=source_size_bytes
    )
    if (isinstance(target_size_bytes, bool) or not isinstance(target_size_bytes, int)
            or target_size_bytes <= 0 or target_size_bytes >= source_size_bytes
            or target_size_bytes % sector_size):
        raise GPTBinaryError("target size must be a smaller positive sector-aligned size")
    target_sectors = target_size_bytes // sector_size
    count = int(source["entry_count"])
    entry_size = int(source["entry_size"])
    array_bytes = count * entry_size
    array_sectors = (array_bytes + sector_size - 1) // sector_size
    primary_entries_lba = 2
    backup_header_lba = target_sectors - 1
    backup_entries_lba = backup_header_lba - array_sectors
    first_usable = int(source["first_usable_lba"])
    last_usable = backup_entries_lba - 1
    if last_usable < first_usable:
        raise GPTBinaryError("target cannot contain GPT metadata and usable partition space")

    source_parts = tuple(source["partitions"])
    plans = tuple(planned_partitions)
    if len(plans) != len(source_parts):
        raise GPTBinaryError("planned partition count differs from source GPT")
    source_by_number = {int(p["number"]): p for p in source_parts}
    raw_array = bytearray(_read_at(
        source_stream, int(source["primary_entries_lba"]) * sector_size, array_bytes
    ))
    seen_numbers: set[int] = set()
    previous_end = first_usable - 1
    for plan in plans:
        number = getattr(plan, "node", None)
        partuuid = getattr(plan, "partuuid", None)
        type_guid = getattr(plan, "type_guid", None)
        start = getattr(plan, "start_sector", None)
        size = getattr(plan, "size_sectors", None)
        if not isinstance(number, str) or not number.startswith("/dev/"):
            raise GPTBinaryError("planned partition has no valid source device node")
        # Device nodes are deliberately not used as GPT slot identifiers.
        # Match the stable partition GUID supplied by the planner instead.
        matches = [p for p in source_parts if p["unique_guid"] == partuuid]
        if len(matches) != 1:
            raise GPTBinaryError("planned partition does not identify exactly one source PARTUUID")
        original = matches[0]
        slot = int(original["number"])
        if slot in seen_numbers:
            raise GPTBinaryError("planned partition repeats a source PARTUUID")
        seen_numbers.add(slot)
        if type_guid is None or str(type_guid).lower() != str(original["type_guid"]).lower():
            raise GPTBinaryError("planned partition type GUID differs from source")
        if (isinstance(start, bool) or not isinstance(start, int)
                or start != int(original["first_lba"])):
            raise GPTBinaryError("GPT rewrite cannot relocate a partition")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise GPTBinaryError("planned partition size is invalid")
        new_end = start + size - 1
        if new_end > int(original["last_lba"]) or new_end > last_usable:
            raise GPTBinaryError("GPT rewrite cannot expand a partition or exceed target geometry")
        previous_end = max(previous_end, new_end)
        offset = (slot - 1) * entry_size
        struct.pack_into("<Q", raw_array, offset + 40, new_end)
    if seen_numbers != set(source_by_number):
        raise GPTBinaryError("planned partitions do not cover every source GPT partition")

    array_crc = _crc32(bytes(raw_array))
    padded_array = bytes(raw_array).ljust(array_sectors * sector_size, b"\\x00")
    disk_guid_raw = uuid.UUID(str(source["disk_guid"])).bytes_le
    revision = 0x00010000
    header_size = _HEADER.size

    def make_header(current: int, backup: int, entries_lba: int) -> bytes:
        sector = bytearray(sector_size)
        _HEADER.pack_into(
            sector, 0, _SIGNATURE, revision, header_size, 0, 0,
            current, backup, first_usable, last_usable, disk_guid_raw,
            entries_lba, count, entry_size, array_crc,
        )
        crc = _crc32(bytes(sector[:header_size]))
        struct.pack_into("<I", sector, 16, crc)
        return bytes(sector)

    mbr = bytearray(_read_at(source_stream, 0, 512))
    mbr[446:510] = bytes(64)
    protective_size = min(target_sectors - 1, 0xFFFFFFFF)
    mbr[446:462] = struct.pack(
        "<B3sB3sII", 0, b"\\x00\\x02\\x00", 0xEE,
        b"\\xff\\xff\\xff", 1, protective_size,
    )
    patches = (
        (0, bytes(mbr)),
        (sector_size, make_header(1, backup_header_lba, primary_entries_lba)),
        (primary_entries_lba * sector_size, padded_array),
        (backup_entries_lba * sector_size, padded_array),
        (backup_header_lba * sector_size, make_header(
            backup_header_lba, 1, backup_entries_lba
        )),
    )
    return patches
