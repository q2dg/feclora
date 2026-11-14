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


_UUID = re.compile(r"^Label:\s*(.*?)\s+uuid:\s*([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})\s*$")
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
        if line.lstrip().startswith("Label:"):
            raise BtrfsInventoryError("Btrfs returned an invalid filesystem UUID or label row")
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
    seen_uuids: set[str] = set()
    for filesystem in filesystems:
        filesystem_uuid = filesystem["uuid"].lower()
        if filesystem_uuid in seen_uuids:
            raise BtrfsInventoryError("Btrfs reported a duplicate filesystem UUID")
        seen_uuids.add(filesystem_uuid)
        filesystem["uuid"] = filesystem_uuid
        expected = filesystem["total_devices"]
        devices = filesystem["devices"]
        actual = len(devices)
        if expected is None or expected < 1 or actual == 0 or actual != expected:
            raise BtrfsInventoryError(
                f"Btrfs filesystem {filesystem['uuid']} reports {expected} devices but lists {actual}"
            )
        seen_devids: set[int] = set()
        seen_paths: set[str] = set()
        for device in devices:
            devid = device["devid"]
            size_bytes = device["size_bytes"]
            path = device["path"]
            if devid < 1 or devid in seen_devids:
                raise BtrfsInventoryError("Btrfs filesystem contains an invalid or duplicate device ID")
            if size_bytes <= 0 or not path.startswith("/dev/"):
                raise BtrfsInventoryError("Btrfs filesystem contains a missing or invalid member device")
            if path in seen_paths:
                raise BtrfsInventoryError("Btrfs filesystem lists a member device more than once")
            seen_devids.add(devid)
            seen_paths.add(path)
    return filesystems



_PROFILE = re.compile(
    r"^\s*(Data|Metadata|System|GlobalReserve),\s*([^:]+):\s*"
    r"total=(\d+)\s+used=(\d+)\s*$", re.IGNORECASE,
)
_KNOWN_PROFILES = {
    "single", "dup", "raid0", "raid1", "raid1c3", "raid1c4",
    "raid10", "raid5", "raid6",
}


def parse_filesystem_profiles(payload: str) -> list[dict[str, Any]]:
    """Parse allocation profiles from 'btrfs filesystem df --raw'."""
    profiles: list[dict[str, Any]] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        match = _PROFILE.match(line)
        if match is None:
            # df output may include harmless non-profile lines, but malformed
            # rows that look like allocation profiles must not be guessed.
            if re.match(r"^\s*(Data|Metadata|System|GlobalReserve)\s*,", line, re.IGNORECASE):
                raise BtrfsInventoryError("Btrfs returned an unrecognized allocation-profile row")
            continue
        kind, profile, total, used = match.groups()
        normalized = profile.strip().lower()
        if not normalized or int(total) < 0 or int(used) < 0 or int(used) > int(total):
            raise BtrfsInventoryError("Btrfs returned invalid allocation-profile sizes")
        profiles.append({
            "type": kind.lower(),
            "profile": normalized,
            "total_bytes": int(total),
            "used_bytes": int(used),
            "known_profile": normalized in _KNOWN_PROFILES,
        })
    if not any(item["type"] == "data" for item in profiles):
        raise BtrfsInventoryError("Btrfs allocation report has no Data profile")
    if not any(item["type"] == "metadata" for item in profiles):
        raise BtrfsInventoryError("Btrfs allocation report has no Metadata profile")
    return profiles


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



_ROOT_ITEM_HEADER = re.compile(r"^\s*item\s+\d+\s+key\s+\((\d+)\s+ROOT_ITEM\s+(\d+)\)")
_ROOT_BACKREF_HEADER = re.compile(r"^\s*item\s+\d+\s+key\s+\((\d+)\s+ROOT_BACKREF\s+(\d+)\)")
_ROOT_DATA = re.compile(
    r"^\s*generation\s+(\d+)\s+root_dirid\s+(\d+)\s+bytenr\s+(\d+)"
    r"\s+byte_limit\s+(\d+)\s+bytes_used\s+(\d+)\s*$"
)
_ROOT_FLAGS = re.compile(
    r"^\s*last_snapshot\s+(\d+)\s+flags\s+(0x[0-9a-fA-F]+)\(([^)]*)\)\s+refs\s+(\d+)\s*$"
)
_ROOT_BACKREF_DATA = re.compile(
    r"^\s*root backref key dirid\s+(\d+)\s+sequence\s+(\d+)\s+name\s+(.*)$"
)
_UUID_VALUE = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _optional_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    if not _UUID_VALUE.fullmatch(value):
        raise BtrfsInventoryError("Btrfs root tree contains an invalid subvolume UUID")
    normalized = value.lower()
    return None if normalized == _ZERO_UUID else normalized


def parse_root_tree_subvolumes(payload: str) -> list[dict[str, Any]]:
    """Parse current subvolume roots and their ancestry from an unmounted root-tree dump.

    Only ROOT_ITEM entries and ROOT_BACKREF records are consumed. File-tree
    contents are deliberately ignored. ROOT_ITEM key offsets are retained;
    btrfs-progs uses a non-zero offset to identify snapshot roots.
    """
    roots: dict[int, dict[str, Any]] = {}
    backrefs: dict[int, dict[str, Any]] = {}
    current_root: dict[str, Any] | None = None
    current_backref_id: int | None = None

    for line in payload.splitlines():
        root_header = _ROOT_ITEM_HEADER.match(line)
        backref_header = _ROOT_BACKREF_HEADER.match(line)
        if root_header:
            subvolume_id, root_offset = (int(value) for value in root_header.groups())
            current_backref_id = None
            current_root = None
            if subvolume_id < 256:
                continue
            if subvolume_id in roots:
                raise BtrfsInventoryError(
                    f"Btrfs root tree contains duplicate current ROOT_ITEM for subvolume {subvolume_id}"
                )
            current_root = {
                "id": subvolume_id,
                "root_item_offset": root_offset,
                "generation": None,
                "root_dirid": None,
                "bytenr": None,
                "byte_limit": None,
                "bytes_used": None,
                "flags": None,
                "readonly": False,
                "refs": None,
                "uuid": None,
                "parent_uuid": None,
                "received_uuid": None,
            }
            roots[subvolume_id] = current_root
            continue
        if backref_header:
            child_id, parent_id = (int(value) for value in backref_header.groups())
            current_root = None
            current_backref_id = child_id if child_id >= 256 else None
            if current_backref_id is not None:
                candidate = {"parent_id": parent_id, "parent_dirid": None, "sequence": None, "name": None}
                previous = backrefs.get(child_id)
                if previous is not None and previous["parent_id"] != parent_id:
                    raise BtrfsInventoryError(
                        f"Btrfs subvolume {child_id} has conflicting parent ROOT_BACKREF records"
                    )
                backrefs[child_id] = candidate
            continue
        if current_root is not None:
            match = _ROOT_DATA.match(line)
            if match:
                (current_root["generation"], current_root["root_dirid"],
                 current_root["bytenr"], current_root["byte_limit"],
                 current_root["bytes_used"]) = (int(value) for value in match.groups())
                continue
            match = _ROOT_FLAGS.match(line)
            if match:
                last_snapshot, flags, flag_names, refs = match.groups()
                current_root["flags"] = int(flags, 16)
                current_root["readonly"] = "RDONLY" in flag_names.split("|")
                current_root["refs"] = int(refs)
                current_root["last_snapshot"] = int(last_snapshot)
                continue
            for field in ("uuid", "parent_uuid", "received_uuid"):
                prefix = field + " "
                if line.strip().startswith(prefix):
                    current_root[field] = _optional_uuid(line.strip()[len(prefix):])
                    break
        if current_backref_id is not None:
            match = _ROOT_BACKREF_DATA.match(line)
            if match:
                parent_dirid, sequence, name = match.groups()
                backrefs[current_backref_id].update({
                    "parent_dirid": int(parent_dirid),
                    "sequence": int(sequence),
                    "name": name if name and not any(ord(char) < 32 for char in name) else None,
                })
                current_backref_id = None

    uuid_to_id = {
        root["uuid"]: subvolume_id
        for subvolume_id, root in roots.items()
        if root["uuid"] is not None
    }
    result: list[dict[str, Any]] = []
    for subvolume_id, root in roots.items():
        if root["generation"] is None or root["bytes_used"] is None:
            raise BtrfsInventoryError(
                f"Btrfs ROOT_ITEM for subvolume {subvolume_id} is incomplete"
            )
        parent_uuid = root["parent_uuid"]
        received_uuid = root["received_uuid"]
        is_snapshot = parent_uuid is not None or root["root_item_offset"] > 0
        if root["uuid"] is None:
            kind = "unknown"
        elif is_snapshot:
            kind = "snapshot"
        elif received_uuid is not None:
            kind = "received_subvolume"
        else:
            kind = "subvolume"
        record = dict(root)
        record.update({
            "kind": kind,
            "is_snapshot": is_snapshot,
            "parent_subvolume_id": uuid_to_id.get(parent_uuid) if parent_uuid else None,
            "parent_id": None,
            "parent_dirid": None,
            "sequence": None,
            "name": None,
            "path": None,
            "metadata_complete": root["uuid"] is not None,
        })
        record.update(backrefs.get(subvolume_id, {}))
        result.append(record)

    by_id = {item["id"]: item for item in result}

    def resolve_path(subvolume_id: int, visiting: set[int]) -> str | None:
        if subvolume_id in visiting:
            raise BtrfsInventoryError("Btrfs ROOT_BACKREF ancestry contains a cycle")
        item = by_id[subvolume_id]
        parent_id, name = item.get("parent_id"), item.get("name")
        if not isinstance(parent_id, int) or not isinstance(name, str) or not name:
            return None
        if parent_id == 5:
            return name
        if parent_id not in by_id:
            return None
        parent_path = resolve_path(parent_id, visiting | {subvolume_id})
        return f"{parent_path}/{name}" if parent_path else None

    for item in result:
        item["path"] = resolve_path(item["id"], set())
    return sorted(result, key=lambda item: item["id"])


_CHUNK_HEADER = re.compile(
    r"^\s*item\s+\d+\s+key\s+\((?:FIRST_CHUNK_TREE|\d+)\s+CHUNK_ITEM\s+(\d+)\)"
)
_CHUNK_DATA = re.compile(
    r"^\s*length\s+(\d+)\s+owner\s+(\d+)\s+stripe_len\s+(\d+)\s+type\s+([A-Z0-9_|.x]+)\s*$"
)
_CHUNK_STRIPE_COUNT = re.compile(r"^\s*num_stripes\s+(\d+)\s+sub_stripes\s+(\d+)\s*$")
_CHUNK_STRIPE = re.compile(r"^\s*stripe\s+(\d+)\s+devid\s+(\d+)\s+offset\s+(\d+)\s*$")


def _allocation_type_and_profile(type_flags: str) -> tuple[str, str, bool]:
    tokens = [token.strip().upper() for token in type_flags.split("|") if token.strip()]
    kinds = [token.lower() for token in tokens if token in {"DATA", "METADATA", "SYSTEM"}]
    if not kinds:
        raise BtrfsInventoryError("Btrfs chunk has no recognized allocation type")
    profile_tokens = [
        token.lower() for token in tokens
        if token not in {"DATA", "METADATA", "SYSTEM", "METADATA_REMAP"}
    ]
    profile = profile_tokens[0] if profile_tokens else "single"
    return "+".join(sorted(kinds)), profile, profile in _KNOWN_PROFILES


def parse_chunk_tree(
    payload: str,
    *,
    known_device_ids: set[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse unmounted chunk-tree layout into per-chunk and profile summaries."""
    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish_chunk() -> None:
        if current is None:
            return
        if (current.get("length_bytes") is None or current.get("num_stripes") is None
                or not isinstance(current.get("type_flags"), str)):
            raise BtrfsInventoryError("Btrfs chunk-tree item is incomplete")
        stripes = current["stripes"]
        if len(stripes) != current["num_stripes"]:
            raise BtrfsInventoryError(
                f"Btrfs chunk at {current['logical_start']} reports {current['num_stripes']} stripes but lists {len(stripes)}"
            )
        if {stripe["index"] for stripe in stripes} != set(range(current["num_stripes"])):
            raise BtrfsInventoryError("Btrfs chunk contains invalid or duplicate stripe indexes")
        kind, profile, known_profile = _allocation_type_and_profile(current["type_flags"])
        device_ids = sorted({stripe["devid"] for stripe in stripes})
        complete = (
            known_device_ids is None
            or all(device_id in known_device_ids for device_id in device_ids)
        )
        chunks.append({
            **current,
            "type": kind,
            "profile": profile,
            "known_profile": known_profile,
            "device_ids": device_ids,
            "device_mapping_complete": complete,
        })

    for line in payload.splitlines():
        header = _CHUNK_HEADER.match(line)
        if header:
            finish_chunk()
            current = {
                "logical_start": int(header.group(1)),
                "length_bytes": None,
                "owner": None,
                "stripe_len_bytes": None,
                "type_flags": None,
                "num_stripes": None,
                "sub_stripes": None,
                "stripes": [],
            }
            continue
        if current is None:
            continue
        match = _CHUNK_DATA.match(line)
        if match:
            length, owner, stripe_len, type_flags = match.groups()
            current.update({
                "length_bytes": int(length),
                "owner": int(owner),
                "stripe_len_bytes": int(stripe_len),
                "type_flags": type_flags,
            })
            continue
        match = _CHUNK_STRIPE_COUNT.match(line)
        if match:
            current["num_stripes"], current["sub_stripes"] = (
                int(value) for value in match.groups()
            )
            if current["num_stripes"] < 1 or current["sub_stripes"] < 0:
                raise BtrfsInventoryError("Btrfs chunk reports an invalid stripe count")
            continue
        match = _CHUNK_STRIPE.match(line)
        if match:
            index, devid, offset = (int(value) for value in match.groups())
            if devid < 1:
                raise BtrfsInventoryError("Btrfs chunk references an invalid device ID")
            current["stripes"].append({
                "index": index, "devid": devid, "offset_bytes": offset,
            })
    finish_chunk()

    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in chunks:
        key = (chunk["type"], chunk["profile"])
        summary = aggregates.setdefault(key, {
            "type": chunk["type"],
            "profile": chunk["profile"],
            "known_profile": chunk["known_profile"],
            "chunk_count": 0,
            "total_bytes": 0,
            "used_bytes": None,
            "device_ids": set(),
            "device_mapping_complete": True,
            "source": "unmounted_chunk_tree",
        })
        summary["chunk_count"] += 1
        summary["total_bytes"] += chunk["length_bytes"]
        summary["device_ids"].update(chunk["device_ids"])
        summary["device_mapping_complete"] = (
            summary["device_mapping_complete"] and chunk["device_mapping_complete"]
        )
    profiles = []
    for summary in aggregates.values():
        summary["device_ids"] = sorted(summary["device_ids"])
        profiles.append(summary)
    profiles.sort(key=lambda item: (item["type"], item["profile"]))
    return chunks, profiles

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
            usage = runner(
                [*prefix, btrfs, "filesystem", "df", "--raw", target],
                check=True, capture_output=True, text=True, timeout=30,
            )
            mounts.append({
                "mountpoint": target,
                "source": entry.get("source"),
                "uuid": entry.get("uuid"),
                "subvolumes": parse_subvolume_list(listed.stdout),
                "allocation_profiles": parse_filesystem_profiles(usage.stdout),
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
    filesystems = parse_filesystem_show(completed.stdout)
    for filesystem in filesystems:
        device_paths = [device["path"] for device in filesystem["devices"]]
        try:
            dump = runner(
                [*prefix, executable, "inspect-internal", "dump-tree",
                 "--noscan", "-t", "root", *device_paths],
                check=True, capture_output=True, text=True, timeout=60,
            )
            filesystem["subvolumes"] = parse_root_tree_subvolumes(dump.stdout)
            filesystem["subvolume_inventory_status"] = "available"
        except subprocess.TimeoutExpired:
            filesystem["subvolumes"] = []
            filesystem["subvolume_inventory_status"] = "error"
            filesystem["subvolume_inventory_error"] = "Btrfs root-tree inspection timed out"
        except subprocess.CalledProcessError as exc:
            filesystem["subvolumes"] = []
            filesystem["subvolume_inventory_status"] = "error"
            filesystem["subvolume_inventory_error"] = (
                (exc.stderr or "").strip() or "Btrfs root-tree inspection failed"
            )
        except BtrfsInventoryError as exc:
            filesystem["subvolumes"] = []
            filesystem["subvolume_inventory_status"] = "error"
            filesystem["subvolume_inventory_error"] = str(exc)

        try:
            chunk_dump = runner(
                [*prefix, executable, "inspect-internal", "dump-tree",
                 "--noscan", "-t", "chunk", *device_paths],
                check=True, capture_output=True, text=True, timeout=60,
            )
            known_device_ids = {device["devid"] for device in filesystem["devices"]}
            chunks, profiles = parse_chunk_tree(
                chunk_dump.stdout, known_device_ids=known_device_ids,
            )
            filesystem["chunks"] = chunks
            filesystem["allocation_profiles"] = profiles
            filesystem["allocation_profile_status"] = "available"
        except subprocess.TimeoutExpired:
            filesystem["chunks"] = []
            filesystem["allocation_profiles"] = []
            filesystem["allocation_profile_status"] = "error"
            filesystem["allocation_profile_error"] = "Btrfs chunk-tree inspection timed out"
        except subprocess.CalledProcessError as exc:
            filesystem["chunks"] = []
            filesystem["allocation_profiles"] = []
            filesystem["allocation_profile_status"] = "error"
            filesystem["allocation_profile_error"] = (
                (exc.stderr or "").strip() or "Btrfs chunk-tree inspection failed"
            )
        except BtrfsInventoryError as exc:
            filesystem["chunks"] = []
            filesystem["allocation_profiles"] = []
            filesystem["allocation_profile_status"] = "error"
            filesystem["allocation_profile_error"] = str(exc)
    return {"status": "available", "filesystems": filesystems}
