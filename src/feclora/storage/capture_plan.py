"""Read-only, conservative capture planning for layered storage.

The planner describes byte scope and dependencies. It never activates volume
groups, opens LUKS mappings, mounts filesystems, creates snapshots, or writes.
"""
from __future__ import annotations

from typing import Any


class CapturePlanError(ValueError):
    """A requested source is absent or cannot be identified unambiguously."""


def _walk_devices(items: list[dict[str, Any]]):
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item
        yield from _walk_devices(item.get("children") or [])


def plan_storage_capture(
    inventory: dict[str, Any],
    source_path: str,
    image_type: str,
) -> dict[str, Any]:
    """Describe a disk/partition's raw-byte scope and storage dependencies."""
    if image_type not in {"disk", "partition", "logical_volume"}:
        raise CapturePlanError("image_type must be disk, partition or logical_volume")
    if not isinstance(source_path, str) or not source_path.startswith("/dev/"):
        raise CapturePlanError("source_path must be an absolute /dev path")
    matches = [item for item in _walk_devices(inventory.get("devices") or [])
               if item.get("path") == source_path]
    if len(matches) != 1:
        raise CapturePlanError("capture source must exist exactly once in the current inventory")
    source = matches[0]
    expected_types = {"disk"} if image_type == "disk" else ({"part"} if image_type == "partition" else {"lvm", "crypt", "dm"})
    if source.get("type") not in expected_types:
        raise CapturePlanError(f"selected source is not a valid {image_type} block device")

    descendants = list(_walk_devices([source]))
    included_paths = {item.get("path") for item in descendants if isinstance(item.get("path"), str)}
    graph = inventory.get("storage_graph") or {}
    nodes = {item.get("id"): item for item in graph.get("nodes", []) if isinstance(item, dict)}
    edges = graph.get("edges") or []
    blockers: list[str] = []
    warnings: list[str] = []
    dependencies: list[dict[str, Any]] = []
    layers: list[str] = []
    capture_scope = "whole_disk_bytes" if image_type == "disk" else "partition_bytes"

    fstype = str(source.get("filesystem") or "").lower()
    features = set(source.get("volume_features") or [])
    if fstype == "crypto_luks" or "luks_container" in features:
        capture_scope = "encrypted_container_bytes"
        layers.append("luks2_container")
        luks_uuid = next((item.get("uuid") for item in (inventory.get("luks_metadata") or {}).get("containers", [])
                          if item.get("device") == source_path), None)
        dependencies.append({
            "kind": "luks2_metadata", "uuid": luks_uuid,
            "included_in_source_bytes": True,
            "restore_note": "Raw encrypted bytes include the LUKS header and keyslots; passphrases and recovery keys are not captured.",
        })
    elif source.get("type") == "crypt" or "crypt_mapping" in features:
        capture_scope = "decrypted_mapping_bytes"
        layers.append("active_crypt_mapping")
        warnings.append("This captures the opened mapping's plaintext block contents, not its LUKS header or keyslots.")
        dependencies.append({
            "kind": "encryption_mapping", "included_in_source_bytes": False,
            "restore_note": "Recreating encryption requires a separately authorized LUKS2 destination and key-management workflow.",
        })

    if fstype == "lvm2_member" or "lvm_pv" in features:
        layers.append("lvm_physical_volume")
        topology = inventory.get("volume_topology") or {}
        pv = next((item for item in topology.get("pvs", []) if item.get("pv_name") == source_path), None)
        dependencies.append({
            "kind": "lvm_pv_metadata", "vg_name": pv.get("vg_name") if pv else None,
            "included_in_source_bytes": True,
            "restore_note": "PV bytes include on-disk LVM metadata; a complete VG may require every member PV.",
        })
        if pv and pv.get("vg_name"):
            members = [item.get("pv_name") for item in topology.get("pvs", [])
                       if item.get("vg_name") == pv.get("vg_name") and item.get("pv_name")]
            complete = set(members).issubset(included_paths)
            dependencies.append({
                "kind": "lvm_vg_members", "vg_name": pv.get("vg_name"),
                "required_device_paths": sorted(set(members)),
                "included_in_source_bytes": complete,
            })
            if not complete:
                blockers.append("The selected source does not contain every PV required by its volume group.")

    for node in nodes.values():
        if node.get("kind") != "lvm_logical_volume":
            continue
        linked = any(edge.get("source") == node.get("id")
                     and edge.get("target") == "device:" + source_path
                     and edge.get("relation") == "maps_to_block_device" for edge in edges)
        if linked:
            layers.append("lvm_logical_volume")
            vg_node = next((edge.get("source") for edge in edges
                            if edge.get("target") == node.get("id")
                            and edge.get("relation") == "contains_lv"), None)
            dependencies.append({
                "kind": "lvm_volume_group", "volume_group_node": vg_node,
                "included_in_source_bytes": False,
                "restore_note": "LV data bytes do not recreate VG/LV geometry, thin-pool metadata or snapshot relationships.",
            })
            warnings.append("A logical-volume image is not a self-contained VG backup; restore requires a separately validated LV layout.")

    for filesystem in (inventory.get("btrfs_topology") or {}).get("filesystems", []):
        member_paths = {item.get("path") for item in filesystem.get("devices", [])
                        if isinstance(item, dict) and isinstance(item.get("path"), str)}
        if not (member_paths & included_paths):
            continue
        layers.append("btrfs_filesystem")
        complete = member_paths.issubset(included_paths)
        dependencies.append({
            "kind": "btrfs_filesystem", "uuid": filesystem.get("uuid"),
            "required_device_paths": sorted(member_paths),
            "total_devices": filesystem.get("total_devices"),
            "included_in_source_bytes": complete,
            "restore_note": "Btrfs filesystem profiles and all member devices must be restored as a coordinated set.",
        })
        if not complete:
            blockers.append("The selected source omits one or more devices belonging to this Btrfs filesystem.")

    for pool in (inventory.get("stratis_topology") or {}).get("pools", []):
        for filesystem in pool.get("filesystems", []):
            if filesystem.get("mapper_device") == source_path or filesystem.get("device") == source_path:
                layers.append("stratis_filesystem")
                blockers.append("Standalone Stratis filesystem imaging is unsupported until pool metadata and all backing devices can be captured and restored together.")
                dependencies.append({
                    "kind": "stratis_pool", "pool": pool.get("name"),
                    "filesystem": filesystem.get("name"),
                    "required_device_paths": list(filesystem.get("backing_device_paths") or []),
                    "included_in_source_bytes": False,
                })

    if graph.get("status") != "available":
        warnings.append("Storage topology is incomplete; inspect unresolved relationships before relying on layer-aware restore.")
    if any(item.get("mountpoints") for item in descendants):
        blockers.append("The selected source or one of its descendants is mounted or in use; a consistent capture snapshot is not established.")
    if source.get("read_only"):
        warnings.append("The selected source is read-only; capture still requires source-access and consistency checks.")

    return {
        "schema_version": 1,
        "source": {
            "path": source_path, "type": image_type,
            "size_bytes": source.get("size_bytes"),
            "filesystem": source.get("filesystem"), "uuid": source.get("uuid"),
            "major_minor": source.get("major_minor"), "wwn": source.get("wwn"),
            "serial": source.get("serial"),
        },
        "capture_scope": capture_scope,
        "storage_layers": list(dict.fromkeys(layers)),
        "dependencies": dependencies,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "eligible_for_layer_aware_capture": not blockers,
        "raw_block_copy_remains_possible": True,
    }
