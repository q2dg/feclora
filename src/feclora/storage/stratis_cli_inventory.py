"""Read-only Stratis CLI metadata parsing.

The parser intentionally leaves unrecognized capacities and identities unknown.
"""
from __future__ import annotations

import re
from typing import Any

_SIZE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(B|bytes?|KiB|MiB|GiB|TiB|KB|MB|GB|TB)\s*$", re.I)
_FACTORS = {"b": 1, "byte": 1, "bytes": 1, "kib": 1024, "mib": 1024**2,
            "gib": 1024**3, "tib": 1024**4, "kb": 1000, "mb": 1000**2,
            "gb": 1000**3, "tb": 1000**4}


def size_bytes(value: str) -> int | None:
    match = _SIZE.fullmatch(value)
    if not match:
        return None
    try:
        return int(float(match.group(1)) * _FACTORS[match.group(2).lower()])
    except (ValueError, OverflowError):
        return None


def _rows(payload: str, count: int) -> list[list[str]]:
    result = []
    for line in payload.splitlines():
        if not line.strip() or set(line.strip()) <= {"-", " "}:
            continue
        columns = [part.strip() for part in re.split(r"\s{2,}", line.strip())]
        if len(columns) == count:
            result.append(columns)
    return result


def _usage(value: str) -> tuple[int | None, int | None, int | None]:
    fields = [field.strip() for field in value.split("/")]
    if len(fields) < 3:
        return None, None, None
    return tuple(size_bytes(field) for field in fields[:3])


def parse_pool_list(payload: str) -> dict[str, dict[str, Any]]:
    result = {}
    for name, usage, properties, uuid, alerts in _rows(payload, 5):
        if name.lower() in {"name", "pool"} or not name:
            continue
        total, used, free = _usage(usage)
        result[name] = {
            "uuid": uuid if re.fullmatch(r"[0-9a-fA-F-]{16,64}", uuid) else None,
            "total_physical_bytes": total, "used_physical_bytes": used,
            "free_physical_bytes": free, "properties": properties,
            "alerts": [] if alerts in {"", "-"} else re.split(r"[,; ]+", alerts),
            "status": "healthy" if alerts in {"", "-"} and total is not None and free is not None else "unknown",
        }
    return result


def parse_filesystem_list(payload: str) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for pool, name, usage, _created, device, uuid in _rows(payload, 6):
        if pool.lower() == "pool" or name.lower() == "filesystem" or not pool or not name:
            continue
        total, used, free = _usage(usage)
        result[(pool, name)] = {
            "uuid": uuid if re.fullmatch(r"[0-9a-fA-F-]{16,64}", uuid) else None,
            "logical_size_bytes": total, "used_bytes": used, "free_bytes": free,
            "device": device if device.startswith("/dev/") else None,
        }
    return result
