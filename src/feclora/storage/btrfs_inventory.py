"""Read-only Btrfs multi-device inventory from btrfs-progs."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Callable


class BtrfsInventoryError(RuntimeError):
    """Btrfs returned invalid device topology."""


_UUID = re.compile(r"^Label:\s*(.*?)\s+uuid:\s*([0-9a-fA-F-]{36})\s*$")
_DEVICE = re.compile(r"^\s*devid\s+(\d+)\s+size\s+(\d+)\s+path\s+(.+?)\s*$")


def parse_filesystem_show(payload: str) -> list[dict[str, Any]]:
    """Parse btrfs filesystem show --raw --all-devices output."""
    filesystems: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in payload.splitlines():
        match = _UUID.match(line)
        if match:
            if current is not None:
                filesystems.append(current)
            label, uuid = match.groups()
            current = {"label": None if label == "none" else label, "uuid": uuid, "devices": []}
            continue
        match = _DEVICE.match(line)
        if match and current is not None:
            devid, size, path = match.groups()
            current["devices"].append({
                "devid": int(devid), "size_bytes": int(size), "path": path,
            })
    if current is not None:
        filesystems.append(current)
    for filesystem in filesystems:
        if not filesystem["devices"]:
            raise BtrfsInventoryError(
                f"Btrfs filesystem {filesystem['uuid']} has no listed devices"
            )
    return filesystems


def collect_btrfs_topology(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Scan existing Btrfs signatures without mounting or changing filesystems."""
    executable = which("btrfs")
    if executable is None:
        return {"status": "unavailable", "filesystems": []}
    argv = [executable, "filesystem", "show", "--raw", "--all-devices"]
    try:
        completed = runner(
            argv, check=True, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise BtrfsInventoryError("Btrfs device scan timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise BtrfsInventoryError(detail or f"{executable} filesystem show failed") from exc
    return {"status": "available", "filesystems": parse_filesystem_show(completed.stdout)}
