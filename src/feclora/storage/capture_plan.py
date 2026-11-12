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
    capture_scope = {
        "disk": "whole_disk_bytes",
        "partition": "partition_bytes",
        "logical_volume": "logical_volume_bytes",
    }[image_type]

    fstype = str(source.get("filesystem") or "").lower()
    features = set(source.get("volume_features") or [])
    source_is_luks_candidate = (
        fstype == "crypto_luks" or "luks_container" in features
    )
    luks_containers = (inventory.get("luks_metadata") or {}).get("containers", [])
    def verified_luks2(device_path: str):
        matches = [
            item for item in luks_containers
            if isinstance(item, dict) and item.get("device") == device_path
            and item.get("version") == 2 and isinstance(item.get("uuid"), str)
            and item.get("uuid")
        ]
        return matches[0] if len(matches) == 1 else None
    source_luks_metadata = verified_luks2(source_path) if source_is_luks_candidate else None
    source_is_luks_container = source_luks_metadata is not None
    if source_is_luks_candidate and not source_is_luks_container and image_type != "disk":
        blockers.append("The selected LUKS-like container is not verifiably LUKS2; LUKS1 and unknown headers are unsupported.")
    if source_is_luks_container:
        capture_scope = "encrypted_container_bytes"
    # Report encryption/PV layers anywhere inside a whole-disk source too.
    for item in descendants:
        item_path = item.get("path")
        item_fstype = str(item.get("filesystem") or "").lower()
        item_features = set(item.get("volume_features") or [])
        if item_fstype == "crypto_luks" or "luks_container" in item_features:
            luks_metadata = verified_luks2(item_path) if isinstance(item_path, str) else None
            if luks_metadata is None:
                if item_path == source_path and image_type != "disk":
                    # The selected partition/LV must be positively identified as LUKS2.
                    pass
                else:
                    warnings.append(
                        f"LUKS-like layer at {item_path} could not be verified as LUKS2; "
                        "it is recorded only as opaque bytes in a whole-disk image."
                    )
                continue
            layers.append("luks2_container")
            dependencies.append({
                "kind": "luks2_metadata", "device_path": item_path,
                "uuid": luks_metadata["uuid"],
                "included_in_source_bytes": True,
                "restore_note": "Raw encrypted bytes include the LUKS2 header and keyslots; passphrases and recovery keys are not captured.",
            })
        if item_fstype == "lvm2_member" or "lvm_pv" in item_features:
            layers.append("lvm_physical_volume")
            topology = inventory.get("volume_topology") or {}
            pv = next((entry for entry in topology.get("pvs", []) if entry.get("pv_name") == item_path), None)
            dependencies.append({
                "kind": "lvm_pv_metadata", "device_path": item_path,
                "vg_name": pv.get("vg_name") if pv else None,
                "included_in_source_bytes": True,
                "restore_note": "PV bytes include on-disk LVM metadata; a complete VG may require every member PV.",
            })
            if pv and pv.get("vg_name"):
                members = [entry.get("pv_name") for entry in topology.get("pvs", [])
                           if entry.get("vg_name") == pv.get("vg_name") and entry.get("pv_name")]
                complete = set(members).issubset(included_paths)
                dependencies.append({
                    "kind": "lvm_vg_members", "vg_name": pv.get("vg_name"),
                    "required_device_paths": sorted(set(members)),
                    "included_in_source_bytes": complete,
                })
                if not complete:
                    blockers.append("The selected source does not contain every PV required by its volume group.")

    # A selected active crypt mapping is plaintext at the block interface.
    if source.get("type") == "crypt" or "crypt_mapping" in features:
        capture_scope = "decrypted_mapping_bytes"
        layers.append("active_crypt_mapping")
        warnings.append("This captures the opened mapping's plaintext block contents, not its LUKS header or keyslots.")
        dependencies.append({
            "kind": "encryption_mapping", "included_in_source_bytes": False,
            "restore_note": "Recreating encryption requires a separately authorized LUKS2 destination and key-management workflow.",
        })

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

    mounted_btrfs_uuids = {
        mount.get("uuid")
        for mount in (inventory.get("btrfs_subvolumes") or {}).get("mounts", [])
        if isinstance(mount, dict) and isinstance(mount.get("uuid"), str)
    }
    for filesystem in (inventory.get("btrfs_topology") or {}).get("filesystems", []):
        member_records = [
            item for item in filesystem.get("devices", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
        member_paths = {item["path"] for item in member_records}
        if not (member_paths & included_paths):
            continue
        layers.append("btrfs_filesystem")
        complete = member_paths.issubset(included_paths)
        filesystem_uuid = filesystem.get("uuid")
        dependencies.append({
            "kind": "btrfs_filesystem", "uuid": filesystem_uuid,
            "required_device_paths": sorted(member_paths),
            "total_devices": filesystem.get("total_devices"),
            "included_in_source_bytes": complete,
            "restore_note": "Btrfs filesystem profiles and all member devices must be restored as a coordinated set.",
        })
        if not complete:
            blockers.append("The selected source omits one or more devices belonging to this Btrfs filesystem.")
        if isinstance(filesystem_uuid, str) and filesystem_uuid in mounted_btrfs_uuids:
            blockers.append("The Btrfs filesystem is mounted; a consistent snapshot has not been established.")
        mount_inventory = inventory.get("btrfs_subvolumes")
        if isinstance(mount_inventory, dict) and mount_inventory.get("status") not in (None, "available"):
            blockers.append("Btrfs mount state could not be verified; refusing a layer-aware consistency claim.")

        profile_status = filesystem.get("allocation_profile_status")
        profiles = filesystem.get("allocation_profiles")
        chunks = filesystem.get("chunks")
        if profile_status is not None:
            if profile_status != "available":
                blockers.append("Btrfs allocation-profile and stripe inventory is unavailable.")
            elif not isinstance(profiles, list) or not profiles or not isinstance(chunks, list) or not chunks:
                blockers.append("Btrfs allocation-profile or chunk dependency inventory is incomplete.")
            else:
                if any(
                    not isinstance(profile, dict) or profile.get("known_profile") is not True
                    for profile in profiles
                ):
                    blockers.append("Btrfs uses an unknown allocation profile; refusing layer-aware capture.")
                member_ids = {
                    item.get("devid") for item in member_records
                    if isinstance(item.get("devid"), int)
                }
                invalid_chunks = [
                    chunk for chunk in chunks
                    if not isinstance(chunk, dict)
                    or chunk.get("device_mapping_complete") is not True
                    or not isinstance(chunk.get("device_ids"), list)
                    or not chunk.get("device_ids")
                    or not set(chunk.get("device_ids", [])).issubset(member_ids)
                ]
                if invalid_chunks:
                    blockers.append("Btrfs chunk stripe-to-device dependencies are incomplete or ambiguous.")
                dependencies.append({
                    "kind": "btrfs_allocation_profiles",
                    "filesystem_uuid": filesystem_uuid,
                    "profiles": profiles,
                    "chunk_dependencies": [
                        {
                            "logical_start": chunk.get("logical_start"),
                            "type": chunk.get("type"),
                            "profile": chunk.get("profile"),
                            "device_ids": chunk.get("device_ids"),
                        }
                        for chunk in chunks if isinstance(chunk, dict)
                    ],
                    "included_in_source_bytes": complete and not invalid_chunks,
                    "restore_note": "Chunk profiles and stripe membership are recorded for compatibility checks; unmounted used-byte accounting is unknown.",
                })

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

    storage_metadata: dict[str, Any] = {
        "schema_version": 1,
        "capture_scope": capture_scope,
        "source_layer": "block_device",
        "dependencies": [],
    }
    if source_is_luks_container:
        storage_metadata["source_layer"] = "luks2_container"
        storage_metadata["luks_uuid"] = source_luks_metadata["uuid"]
    elif source.get("type") == "crypt" or "crypt_mapping" in features:
        storage_metadata["source_layer"] = "active_crypt_mapping"
    elif fstype == "btrfs":
        storage_metadata["source_layer"] = "btrfs_filesystem"
        btrfs_matches = [
            filesystem for filesystem in (inventory.get("btrfs_topology") or {}).get("filesystems", [])
            if any(
                isinstance(device, dict) and device.get("path") == source_path
                for device in filesystem.get("devices", [])
            )
        ]
        btrfs_uuid = source.get("uuid")
        if not btrfs_uuid and len(btrfs_matches) == 1:
            btrfs_uuid = btrfs_matches[0].get("uuid")
        if isinstance(btrfs_uuid, str) and btrfs_uuid:
            storage_metadata["btrfs_uuid"] = btrfs_uuid
        else:
            blockers.append("Btrfs filesystem UUID could not be resolved uniquely; refusing layer-aware capture.")
        if len(btrfs_matches) != 1:
            blockers.append("Btrfs filesystem membership could not be resolved to exactly one complete device set.")
        else:
            device_count = btrfs_matches[0].get("total_devices")
            if isinstance(device_count, bool) or not isinstance(device_count, int) or device_count < 1:
                blockers.append("Btrfs filesystem device count is missing or invalid.")
            else:
                storage_metadata["btrfs_device_count"] = device_count

    for node in nodes.values():
        if node.get("kind") != "lvm_logical_volume":
            continue
        if any(edge.get("source") == node.get("id")
               and edge.get("target") == "device:" + source_path
               and edge.get("relation") == "maps_to_block_device" for edge in edges):
            storage_metadata["source_layer"] = "lvm_logical_volume"
            if node.get("name"):
                storage_metadata["lvm_lv_name"] = str(node["name"])
            if node.get("uuid"):
                storage_metadata["lvm_lv_uuid"] = str(node["uuid"])
            vg_edge = next((edge for edge in edges
                            if edge.get("target") == node.get("id")
                            and edge.get("relation") == "contains_lv"), None)
            vg_node = nodes.get(vg_edge.get("source")) if vg_edge else None
            if vg_node and vg_node.get("name"):
                storage_metadata["lvm_vg_name"] = str(vg_node["name"])
            if vg_node and vg_node.get("uuid"):
                storage_metadata["lvm_vg_uuid"] = str(vg_node["uuid"])
            break

    dependency_kinds = {
        "luks2_metadata", "lvm_pv_metadata", "lvm_vg_members",
        "lvm_volume_group", "btrfs_filesystem",
    }
    for dependency in dependencies:
        kind = dependency.get("kind")
        if kind not in dependency_kinds:
            continue
        identity = dependency.get("uuid") or dependency.get("vg_name")
        if kind == "lvm_volume_group":
            vg_node = nodes.get(dependency.get("volume_group_node"))
            identity = ((vg_node or {}).get("uuid") or (vg_node or {}).get("name")
                        or dependency.get("volume_group_node"))
        if isinstance(identity, str) and identity:
            storage_metadata["dependencies"].append({
                "kind": kind, "identity": identity,
                "included_in_source_bytes": bool(dependency.get("included_in_source_bytes")),
            })

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
        "manifest_storage": storage_metadata,
        "storage_layers": list(dict.fromkeys(layers)),
        "dependencies": dependencies,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "eligible_for_layer_aware_capture": not blockers,
        "raw_block_copy_remains_possible": True,
    }
