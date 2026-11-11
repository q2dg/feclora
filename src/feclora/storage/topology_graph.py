"""Conservative read-only graph joining block devices and storage layers.

Only exact device-path matches create cross-layer edges. Missing or ambiguous
relationships are reported as unresolved instead of being guessed.
"""
from __future__ import annotations

import re
from typing import Any


_DEVICE_PATH = re.compile(r"(/dev/[^\s,()]+)")


def _walk_devices(devices: list[dict[str, Any]]):
    def visit(node: dict[str, Any], parent: str | None = None):
        path = node.get("path") or node.get("name")
        if isinstance(path, str) and path.startswith("/dev/"):
            yield node, parent
            parent = path
        for child in node.get("children") or []:
            if isinstance(child, dict):
                yield from visit(child, parent)
    for device in devices:
        if isinstance(device, dict):
            yield from visit(device)


def build_storage_graph(inventory: dict[str, Any]) -> dict[str, Any]:
    """Join lsblk, LVM, LUKS and Btrfs evidence without inferring aliases."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    path_ids: dict[str, str] = {}

    def add_node(node_id: str, kind: str, **attributes: Any) -> str:
        nodes.setdefault(node_id, {"id": node_id, "kind": kind, **attributes})
        return node_id

    def add_edge(source: str, target: str, relation: str) -> None:
        edge = {"source": source, "target": target, "relation": relation}
        if edge not in edges:
            edges.append(edge)

    devices = inventory.get("devices") or []
    for device, parent_path in _walk_devices(devices):
        path = device.get("path") or device.get("name")
        if not isinstance(path, str):
            continue
        device_id = add_node(
            "device:" + path, "block_device", path=path,
            device_type=device.get("type"), size_bytes=device.get("size_bytes"),
            serial=device.get("serial"), wwn=device.get("wwn"),
            filesystem=device.get("filesystem"), uuid=device.get("uuid"),
            label=device.get("label"), mountpoints=device.get("mountpoints", []),
            volume_features=device.get("volume_features", []),
        )
        path_ids[path] = device_id
        if parent_path:
            add_edge("device:" + parent_path, device_id, "contains")
        filesystem = str(device.get("filesystem") or "").strip()
        if filesystem:
            fs_uuid = device.get("uuid")
            fs_id = add_node(
                "filesystem:" + str(fs_uuid or path), "filesystem",
                filesystem=filesystem, uuid=fs_uuid, label=device.get("label"),
                mountpoints=device.get("mountpoints", []),
            )
            add_edge(device_id, fs_id, "hosts")

    luks = inventory.get("luks_metadata") or {}
    luks_by_path = {
        item.get("device"): item for item in luks.get("containers", [])
        if isinstance(item, dict) and isinstance(item.get("device"), str)
    }
    for path, metadata in luks_by_path.items():
        device_id = path_ids.get(path)
        if not device_id:
            unresolved.append({"layer": "luks", "path": path, "reason": "device_not_in_lsblk"})
            continue
        luks_id = add_node(
            "luks:" + str(metadata.get("uuid") or path), "luks2_container",
            device=path, uuid=metadata.get("uuid"), cipher=metadata.get("cipher"),
            sector_size=metadata.get("sector_size"),
            keyslot_count=metadata.get("keyslot_count"),
            token_count=metadata.get("token_count"),
        )
        add_edge(device_id, luks_id, "contains_encrypted_container")

    # A TYPE=crypt child under a crypto_LUKS device is a proven active mapping.
    for device, parent_path in _walk_devices(devices):
        path = device.get("path") or device.get("name")
        if device.get("type") != "crypt" or not parent_path:
            continue
        parent = next((d for d, _ in _walk_devices(devices)
                       if (d.get("path") or d.get("name")) == parent_path), None)
        if parent and str(parent.get("filesystem") or "").lower() == "crypto_luks":
            add_edge("device:" + parent_path, "device:" + str(path), "opened_as_mapping")

    lvm = inventory.get("volume_topology") or {}
    vg_ids: dict[str, str] = {}
    for vg in lvm.get("volume_groups", []):
        if not isinstance(vg, dict) or not vg.get("name"):
            continue
        name = str(vg["name"])
        vg_id = add_node(
            "lvm-vg:" + name, "lvm_volume_group", name=name,
            uuid=vg.get("uuid"), status=vg.get("status"),
            missing_pv_count=vg.get("missing_pv_count"),
            extent_size_bytes=vg.get("extent_size_bytes"),
        )
        vg_ids[name] = vg_id

    pv_ids: dict[str, str] = {}
    for pv in lvm.get("pvs", []):
        if not isinstance(pv, dict):
            continue
        path = pv.get("pv_name")
        vg_name = str(pv.get("vg_name") or "")
        if not isinstance(path, str) or not path.startswith("/dev/"):
            continue
        pv_id = add_node(
            "lvm-pv:" + str(pv.get("pv_uuid") or path), "lvm_physical_volume",
            path=path, uuid=pv.get("pv_uuid"), size_bytes=pv.get("pv_size"),
            free_bytes=pv.get("pv_free"),
        )
        pv_ids[path] = pv_id
        device_id = path_ids.get(path)
        if device_id:
            add_edge(device_id, pv_id, "contains_pv")
        else:
            unresolved.append({"layer": "lvm_pv", "path": path, "reason": "device_path_not_matched"})
        if vg_name in vg_ids:
            add_edge(pv_id, vg_ids[vg_name], "member_of")

    for vg in lvm.get("volume_groups", []):
        if not isinstance(vg, dict):
            continue
        vg_name = str(vg.get("name") or "")
        vg_id = vg_ids.get(vg_name)
        if not vg_id:
            continue
        for lv in vg.get("logical_volumes", []):
            if not isinstance(lv, dict):
                continue
            lv_path = lv.get("path")
            lv_key = str(lv.get("uuid") or lv_path or (vg_name + "/" + str(lv.get("name"))))
            lv_id = add_node(
                "lvm-lv:" + lv_key, "lvm_logical_volume",
                path=lv_path, name=lv.get("name"), uuid=lv.get("uuid"),
                size_bytes=lv.get("size_bytes"), segment_type=lv.get("segment_type"),
                layout=lv.get("layout"), thin_provisioned=lv.get("thin_provisioned"),
                snapshot=lv.get("snapshot"), origin=lv.get("origin"),
                hidden=lv.get("hidden"), health=lv.get("health"),
            )
            add_edge(vg_id, lv_id, "contains_lv")
            lv_device_path = lv_path if isinstance(lv_path, str) else None
            if lv_device_path and lv_device_path in path_ids:
                add_edge(lv_id, path_ids[lv_device_path], "maps_to_block_device")
            devices_field = lv.get("devices")
            if isinstance(devices_field, str):
                for backing_path in _DEVICE_PATH.findall(devices_field):
                    pv_id = pv_ids.get(backing_path)
                    if pv_id:
                        add_edge(lv_id, pv_id, "allocated_on")
                    else:
                        unresolved.append({
                            "layer": "lvm_lv_backing", "path": backing_path,
                            "reason": "pv_path_not_matched",
                        })

    btrfs = inventory.get("btrfs_topology") or {}
    for filesystem in btrfs.get("filesystems", []):
        if not isinstance(filesystem, dict) or not filesystem.get("uuid"):
            continue
        fs_id = add_node(
            "btrfs:" + str(filesystem["uuid"]), "btrfs_filesystem",
            uuid=filesystem.get("uuid"), label=filesystem.get("label"),
            total_devices=filesystem.get("total_devices"),
        )
        for member in filesystem.get("devices", []):
            if not isinstance(member, dict):
                continue
            path = member.get("path")
            device_id = path_ids.get(path) if isinstance(path, str) else None
            if device_id:
                add_edge(fs_id, device_id, "spans_device")
            elif isinstance(path, str):
                unresolved.append({"layer": "btrfs_member", "path": path, "reason": "device_path_not_matched"})

    subvolumes = inventory.get("btrfs_subvolumes") or {}
    for mount in subvolumes.get("mounts", []):
        if not isinstance(mount, dict):
            continue
        mountpoint = mount.get("mountpoint")
        for subvolume in mount.get("subvolumes", []):
            if not isinstance(subvolume, dict):
                continue
            subvol_id = add_node(
                "btrfs-subvolume:" + str(subvolume.get("uuid") or subvolume.get("id")),
                "btrfs_subvolume", uuid=subvolume.get("uuid"),
                subvolume_id=subvolume.get("id"), path=subvolume.get("path"),
                subvolume_kind=subvolume.get("kind"), parent_uuid=subvolume.get("parent_uuid"),
                received_uuid=subvolume.get("received_uuid"), mountpoint=mountpoint,
            )
            # Mountpoint-to-filesystem UUID resolution is intentionally omitted
            # until findmnt provides the source UUID in the inventory contract.

    return {
        "schema_version": 1,
        "status": "available",
        "nodes": list(nodes.values()),
        "edges": edges,
        "unresolved": unresolved,
    }
