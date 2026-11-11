"""Read-only Btrfs multi-device inventory from btrfs-progs."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable


class BtrfsInventoryError(RuntimeError):
    """Btrfs returned invalid device topology."""


_UUID = re.compile(r"^Label:\s*(.*?)\s+uuid:\s*([0-9a-fA-F-]{36})\s*$")
_TOTAL = re.compile(r"^\s*Total devices\s+(\d+)\b")
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
            current = {
                "label": None if label == "none" else label,
                "uuid": uuid,
                "total_devices": None,
                "devices": [],
            }
            continue
        total_match = _TOTAL.match(line)
        if total_match and current is not None:
            current["total_devices"] = int(total_match.group(1))
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
        expected = filesystem["total_devices"]
        actual = len(filesystem["devices"])
        if expected is None or actual == 0 or actual != expected:
            raise BtrfsInventoryError(
                f"Btrfs filesystem {filesystem['uuid']} reports {expected} devices but lists {actual}"
            )
    return filesystems



_SUBVOLUME = re.compile(
    r"^ID\s+(\d+)\s+gen\s+(\d+)\s+parent\s+(\d+)\s+top level\s+(\d+)"
    r"\s+parent_uuid\s+(\S+)\s+received_uuid\s+(\S+)\s+uuid\s+(\S+)"
    r"\s+path\s+(.+?)\s*$"
)


def parse_subvolume_list(payload: str) -> list[dict[str, Any]]:
    """Parse btrfs subvolume list -a -p -u -q -R output."""
    subvolumes: list[dict[str, Any]] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        match = _SUBVOLUME.match(line)
        if match is None:
            raise BtrfsInventoryError("Btrfs returned an unrecognized subvolume-list row")
        subvol_id, generation, parent_id, top_level, parent_uuid, received_uuid, uuid, path = match.groups()
        has_parent_uuid = parent_uuid not in {"-", "0" * 36}
        has_received_uuid = received_uuid not in {"-", "0" * 36}
        # A received UUID proves receive provenance, not snapshot ancestry.
        # Only parent_uuid is used to classify a snapshot.
        is_snapshot = has_parent_uuid
        snapshot_kind = (
            "snapshot" if has_parent_uuid
            else "received_subvolume" if has_received_uuid
            else "subvolume"
        )
        subvolumes.append({
            "id": int(subvol_id),
            "generation": int(generation),
            "parent_id": int(parent_id),
            "top_level_id": int(top_level),
            "parent_uuid": None if parent_uuid == "-" else parent_uuid,
            "received_uuid": None if received_uuid == "-" else received_uuid,
            "uuid": uuid,
            "path": path,
            "kind": snapshot_kind,
            "is_snapshot": is_snapshot,
        })
    return subvolumes


def collect_btrfs_subvolumes(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    effective_uid: Callable[[], int] = os.geteuid,
    sudo: str | None = None,
) -> dict[str, Any]:
    """Inspect subvolumes on already-mounted Btrfs filesystems only."""
    btrfs = which("btrfs")
    findmnt = which("findmnt")
    if btrfs is None or findmnt is None:
        missing = [name for name, value in (("btrfs", btrfs), ("findmnt", findmnt)) if value is None]
        return {"status": "unavailable", "missing": missing, "mounts": []}
    prefix: list[str] = []
    if effective_uid() != 0:
        sudo_bin = sudo or shutil.which("sudo")
        if not sudo_bin:
            return {"status": "permission_required", "mounts": []}
        prefix = [sudo_bin, "-n"]
    try:
        mounted = runner(
            [*prefix, findmnt, "--json", "--list", "--types", "btrfs", "--output", "TARGET,SOURCE,UUID"],
            check=True, capture_output=True, text=True, timeout=15,
        )
        payload = json.loads(mounted.stdout)
        filesystems = payload.get("filesystems") if isinstance(payload, dict) else None
        if not isinstance(filesystems, list):
            raise BtrfsInventoryError("findmnt returned invalid Btrfs mount JSON")
        mounts: list[dict[str, Any]] = []
        for entry in filesystems:
            target = entry.get("target") if isinstance(entry, dict) else None
            if not isinstance(target, str) or not target.startswith("/"):
                raise BtrfsInventoryError("findmnt returned an invalid Btrfs mountpoint")
            listed = runner(
                [*prefix, btrfs, "subvolume", "list", "-a", "-p", "-u", "-q", "-R", target],
                check=True, capture_output=True, text=True, timeout=30,
            )
            mounts.append({
                "mountpoint": target,
                "source": entry.get("source"),
                "uuid": entry.get("uuid"),
                "subvolumes": parse_subvolume_list(listed.stdout),
            })
    except subprocess.TimeoutExpired as exc:
        raise BtrfsInventoryError("Btrfs subvolume inspection timed out") from exc
    except subprocess.CalledProcessError as exc:
        # findmnt returns 1 when the requested filesystem type has no matches.
        # That is a valid empty inventory, not a failed Btrfs inspection.
        command = [str(part) for part in (exc.cmd or [])]
        if findmnt in command and exc.returncode == 1 and not (exc.stderr or "").strip():
            return {"status": "available", "mounts": []}
        detail = (exc.stderr or "").strip()
        raise BtrfsInventoryError(detail or "Btrfs subvolume inspection failed") from exc
    except json.JSONDecodeError as exc:
        raise BtrfsInventoryError("findmnt returned invalid JSON") from exc
    return {"status": "available", "mounts": mounts}


def collect_btrfs_topology(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    effective_uid: Callable[[], int] = os.geteuid,
    sudo: str | None = None,
) -> dict[str, Any]:
    """Scan existing Btrfs signatures without mounting or changing filesystems."""
    executable = which("btrfs")
    if executable is None:
        return {"status": "unavailable", "filesystems": []}
    prefix: list[str] = []
    if effective_uid() != 0:
        sudo_bin = sudo or shutil.which("sudo")
        if not sudo_bin:
            return {"status": "permission_required", "filesystems": []}
        prefix = [sudo_bin, "-n"]
    argv = [*prefix, executable, "filesystem", "show", "--raw", "--all-devices"]
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
