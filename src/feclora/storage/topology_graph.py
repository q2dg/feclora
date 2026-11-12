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
    """Join storage evidence; never infer an unverified device alias."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    path_ids: dict[str, str] = {}
    device_ids_by_major_minor: dict[str, list[str]] = {}

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
            major_minor=device.get("major_minor"),
            filesystem=device.get("filesystem"), uuid=device.get("uuid"),
            label=device.get("label"), mountpoints=device.get("mountpoints", []),
            volume_features=device.get("volume_features", []),
        )
        path_ids[path] = device_id
        major_minor = device.get("major_minor")
        if isinstance(major_minor, str) and major_minor.count(":") == 1:
            device_ids_by_major_minor.setdefault(major_minor, []).append(device_id)
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
    for item in luks.get("containers", []):
        if not isinstance(item, dict) or not isinstance(item.get("device"), str):
            continue
        path = item["device"]
        device_id = path_ids.get(path)
        if not device_id:
            unresolved.append({"layer": "luks", "path": path, "reason": "device_not_in_lsblk"})
            continue
        luks_id = add_node(
            "luks:" + str(item.get("uuid") or path), "luks2_container",
            device=path, uuid=item.get("uuid"), cipher=item.get("cipher"),
            sector_size=item.get("sector_size"),
            keyslot_count=item.get("keyslot_count"), token_count=item.get("token_count"),
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
        vg_ids[name] = add_node(
            "lvm-vg:" + name, "lvm_volume_group", name=name,
            uuid=vg.get("uuid"), status=vg.get("status"),
            missing_pv_count=vg.get("missing_pv_count"),
            extent_size_bytes=vg.get("extent_size_bytes"),
        )

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
                hidden=lv.get("hidden"), health=lv.get("health"), major_minor=lv.get("major_minor"),
            )
            add_edge(vg_id, lv_id, "contains_lv")
            matched_device_id = path_ids.get(lv_path) if isinstance(lv_path, str) else None
            path_identity_conflict = False
            if matched_device_id:
                matched_device = nodes[matched_device_id]
                lv_major_minor = lv.get("major_minor")
                device_major_minor = matched_device.get("major_minor")
                if (isinstance(lv_major_minor, str) and lv_major_minor
                        and isinstance(device_major_minor, str) and device_major_minor
                        and lv_major_minor != device_major_minor):
                    unresolved.append({"layer": "lvm_lv", "path": str(lv_path),
                                       "reason": "device_path_and_major_minor_conflict"})
                    matched_device_id = None
                    path_identity_conflict = True
            if matched_device_id is None and not path_identity_conflict:
                major_minor = lv.get("major_minor")
                candidates = device_ids_by_major_minor.get(major_minor, []) if isinstance(major_minor, str) else []
                if len(candidates) == 1:
                    matched_device_id = candidates[0]
                elif len(candidates) > 1:
                    unresolved.append({"layer": "lvm_lv", "path": str(lv_path or ""),
                                       "reason": "device_major_minor_is_ambiguous"})
                elif isinstance(lv_path, str) and lv_path:
                    unresolved.append({"layer": "lvm_lv", "path": lv_path,
                                       "reason": "lv_path_and_device_identity_not_matched"})
            if matched_device_id:
                add_edge(lv_id, matched_device_id, "maps_to_block_device")
                matched_device = next((node for node in nodes.values()
                                       if node["id"] == matched_device_id), None)
                if matched_device and matched_device.get("filesystem"):
                    filesystem_uuid = matched_device.get("uuid")
                    filesystem_id = "filesystem:" + str(filesystem_uuid or matched_device.get("path"))
                    if filesystem_id in nodes:
                        add_edge(lv_id, filesystem_id, "hosts_filesystem")

            backing_paths = set()
            devices_field = lv.get("devices")
            if isinstance(devices_field, str):
                backing_paths.update(_DEVICE_PATH.findall(devices_field))
            for backing_path in sorted(backing_paths):
                pv_id = pv_ids.get(backing_path)
                if pv_id:
                    add_edge(lv_id, pv_id, "allocated_on")
                else:
                    unresolved.append({"layer": "lvm_lv_backing", "path": backing_path,
                                       "reason": "pv_path_not_matched"})

    btrfs = inventory.get("btrfs_topology") or {}
    btrfs_fs_ids: dict[str, str] = {}
    subvolume_ids: dict[str, str] = {}
    subvolume_ids_by_local_id: dict[tuple[str, int], str] = {}
    subvolume_parents: list[tuple[str, str]] = []
    subvolume_parent_ids: list[tuple[str, str, int]] = []

    def register_subvolume(
        filesystem_uuid: str,
        filesystem_id: str,
        subvolume: dict[str, Any],
        *,
        mountpoint: str | None = None,
    ) -> str:
        uuid = subvolume.get("uuid")
        local_id = subvolume.get("id")
        identity = (
            str(uuid) if isinstance(uuid, str) and uuid
            else f"{filesystem_uuid}:{local_id}"
        )
        node_id = "btrfs-subvolume:" + identity
        attributes = {
            "uuid": uuid,
            "subvolume_id": local_id,
            "path": subvolume.get("path"),
            "subvolume_kind": subvolume.get("kind"),
            "parent_uuid": subvolume.get("parent_uuid"),
            "received_uuid": subvolume.get("received_uuid"),
            "parent_subvolume_id": subvolume.get("parent_subvolume_id"),
            "parent_id": subvolume.get("parent_id"),
            "parent_dirid": subvolume.get("parent_dirid"),
            "name": subvolume.get("name"),
            "generation": subvolume.get("generation"),
            "bytes_used": subvolume.get("bytes_used"),
            "readonly": subvolume.get("readonly"),
            "is_snapshot": subvolume.get("is_snapshot"),
            "root_item_offset": subvolume.get("root_item_offset"),
            "metadata_complete": subvolume.get("metadata_complete"),
        }
        add_node(node_id, "btrfs_subvolume", **attributes)
        node = nodes[node_id]
        for key, value in attributes.items():
            if value is not None and node.get(key) is None:
                node[key] = value
        if mountpoint:
            node["mountpoint"] = mountpoint
        add_edge(filesystem_id, node_id, "contains_subvolume")
        if isinstance(uuid, str) and uuid:
            subvolume_ids[uuid] = node_id
        if isinstance(local_id, int):
            subvolume_ids_by_local_id[(filesystem_uuid, local_id)] = node_id
        parent_uuid = subvolume.get("parent_uuid")
        if isinstance(parent_uuid, str) and parent_uuid:
            subvolume_parents.append((node_id, parent_uuid))
        parent_subvolume_id = subvolume.get("parent_subvolume_id")
        if isinstance(parent_subvolume_id, int):
            subvolume_parent_ids.append((node_id, filesystem_uuid, parent_subvolume_id))
        return node_id

    for filesystem in btrfs.get("filesystems", []):
        if not isinstance(filesystem, dict) or not filesystem.get("uuid"):
            continue
        uuid = str(filesystem["uuid"])
        fs_id = add_node(
            "btrfs:" + uuid, "btrfs_filesystem", uuid=uuid,
            label=filesystem.get("label"), total_devices=filesystem.get("total_devices"),
        )
        btrfs_fs_ids[uuid] = fs_id
        members_by_devid = {
            member.get("devid"): member
            for member in filesystem.get("devices", [])
            if isinstance(member, dict) and isinstance(member.get("devid"), int)
        }
        for member in filesystem.get("devices", []):
            if not isinstance(member, dict):
                continue
            path = member.get("path")
            device_id = path_ids.get(path) if isinstance(path, str) else None
            if device_id:
                add_edge(fs_id, device_id, "spans_device")
            elif isinstance(path, str):
                unresolved.append({"layer": "btrfs_member", "path": path,
                                   "reason": "device_path_not_matched"})

        fs_node = nodes[fs_id]
        unmounted_profiles = filesystem.get("allocation_profiles")
        profile_status = filesystem.get("allocation_profile_status", "unavailable")
        fs_node["unmounted_allocation_profiles"] = (
            unmounted_profiles if isinstance(unmounted_profiles, list) else []
        )
        fs_node["unmounted_allocation_profile_inventory"] = profile_status
        if isinstance(unmounted_profiles, list):
            fs_node["allocation_profiles"] = unmounted_profiles
            fs_node["allocation_profile_inventory"] = profile_status
            fs_node["has_unknown_allocation_profile"] = any(
                not isinstance(item, dict) or item.get("known_profile") is not True
                for item in unmounted_profiles
            )
        if profile_status == "error":
            unresolved.append({
                "layer": "btrfs_allocation_profile",
                "path": uuid,
                "reason": str(filesystem.get("allocation_profile_error") or "chunk_tree_inspection_failed"),
            })

        for chunk in filesystem.get("chunks", []) or []:
            if not isinstance(chunk, dict):
                continue
            logical_start = chunk.get("logical_start")
            if not isinstance(logical_start, int):
                continue
            chunk_id = f"btrfs-chunk:{uuid}:{logical_start}"
            add_node(
                chunk_id, "btrfs_chunk",
                logical_start=logical_start,
                length_bytes=chunk.get("length_bytes"),
                type=chunk.get("type"),
                profile=chunk.get("profile"),
                known_profile=chunk.get("known_profile"),
                stripe_len_bytes=chunk.get("stripe_len_bytes"),
                num_stripes=chunk.get("num_stripes"),
                sub_stripes=chunk.get("sub_stripes"),
                device_ids=chunk.get("device_ids"),
                stripes=chunk.get("stripes"),
                device_mapping_complete=chunk.get("device_mapping_complete"),
            )
            add_edge(fs_id, chunk_id, "contains_chunk")
            for devid in chunk.get("device_ids", []) or []:
                member = members_by_devid.get(devid)
                path = member.get("path") if isinstance(member, dict) else None
                device_id = path_ids.get(path) if isinstance(path, str) else None
                if device_id:
                    add_edge(chunk_id, device_id, "stripes_on")
                else:
                    unresolved.append({
                        "layer": "btrfs_chunk_stripe",
                        "path": str(path or f"devid:{devid}"),
                        "reason": "chunk_device_not_matched",
                    })

        if filesystem.get("subvolume_inventory_status") == "error":
            unresolved.append({
                "layer": "btrfs_subvolume",
                "path": uuid,
                "reason": str(filesystem.get("subvolume_inventory_error") or "root_tree_inspection_failed"),
            })
        for subvolume in filesystem.get("subvolumes", []) or []:
            if isinstance(subvolume, dict):
                register_subvolume(uuid, fs_id, subvolume)

    subvolumes = inventory.get("btrfs_subvolumes") or {}
    for mount in subvolumes.get("mounts", []):
        if not isinstance(mount, dict):
            continue
        mount_uuid = mount.get("uuid")
        filesystem_id = btrfs_fs_ids.get(mount_uuid) if isinstance(mount_uuid, str) else None
        if filesystem_id is None:
            unresolved.append({"layer": "btrfs_mount", "path": str(mount.get("mountpoint") or ""),
                               "reason": "mount_source_uuid_not_matched"})
            continue
        profiles = mount.get("allocation_profiles")
        fs_node = nodes[filesystem_id]
        if isinstance(profiles, list):
            fs_node["mounted_allocation_profiles"] = profiles
            fs_node["mounted_allocation_profile_inventory"] = "available"
            fs_node["allocation_profiles"] = profiles
            fs_node["allocation_profile_inventory"] = "available"
            fs_node["has_unknown_allocation_profile"] = (
                fs_node.get("has_unknown_allocation_profile", False)
                or any(
                    not isinstance(item, dict) or item.get("known_profile") is not True
                    for item in profiles
                )
            )
        else:
            fs_node["mounted_allocation_profile_inventory"] = "unavailable"
        for subvolume in mount.get("subvolumes", []) or []:
            if isinstance(subvolume, dict):
                register_subvolume(
                    str(mount_uuid), filesystem_id, subvolume,
                    mountpoint=mount.get("mountpoint"),
                )

    for child_id, parent_uuid in subvolume_parents:
        parent_id = subvolume_ids.get(parent_uuid)
        if parent_id:
            add_edge(child_id, parent_id, "snapshot_of")
        else:
            unresolved.append({"layer": "btrfs_snapshot_parent", "path": parent_uuid,
                               "reason": "parent_subvolume_not_in_inventory"})
    for child_id, filesystem_uuid, parent_subvolume_id in subvolume_parent_ids:
        if parent_subvolume_id == 5:
            continue
        parent_id = subvolume_ids_by_local_id.get((filesystem_uuid, parent_subvolume_id))
        if parent_id:
            add_edge(child_id, parent_id, "nested_under")
        else:
            unresolved.append({
                "layer": "btrfs_nested_parent",
                "path": f"{filesystem_uuid}:{parent_subvolume_id}",
                "reason": "parent_subvolume_not_in_inventory",
            })

    stratis = inventory.get("stratis_topology") or {}
    for pool in stratis.get("pools", []):
        if not isinstance(pool, dict) or not isinstance(pool.get("name"), str):
            continue
        pool_name = pool["name"]
        pool_id = add_node("stratis-pool:" + pool_name, "stratis_pool", name=pool_name)
        for filesystem in pool.get("filesystems", []):
            if not isinstance(filesystem, dict) or not isinstance(filesystem.get("name"), str):
                continue
            fs_name = filesystem["name"]
            fs_id = add_node(
                "stratis-filesystem:" + pool_name + "/" + fs_name, "stratis_filesystem",
                name=fs_name, pool=pool_name, device=filesystem.get("device"),
                mapper_device=filesystem.get("mapper_device"),
            )
            add_edge(pool_id, fs_id, "contains_filesystem")
            mapper_path = filesystem.get("mapper_device")
            if isinstance(mapper_path, str):
                mapper_id = path_ids.get(mapper_path)
                if mapper_id:
                    add_edge(fs_id, mapper_id, "maps_to_block_device")
                else:
                    unresolved.append({"layer": "stratis_mapper", "path": mapper_path,
                                       "reason": "device_path_not_matched"})
            for path in filesystem.get("backing_device_paths", []):
                if not isinstance(path, str):
                    continue
                device_id = path_ids.get(path)
                if device_id:
                    add_edge(fs_id, device_id, "backed_by")
                else:
                    unresolved.append({"layer": "stratis_backing", "path": path,
                                       "reason": "device_path_not_matched"})

    source_statuses = []
    for key in ("volume_topology", "luks_metadata", "btrfs_topology",
                "btrfs_subvolumes", "stratis_topology"):
        source = inventory.get(key)
        if isinstance(source, dict) and source.get("status") not in (None, "available"):
            source_statuses.append({"source": key, "status": source.get("status")})
    graph_status = "partial" if unresolved or source_statuses else "available"
    return {
        "schema_version": 1,
        "status": graph_status,
        "source_statuses": source_statuses,
        "nodes": list(nodes.values()),
        "edges": edges,
        "unresolved": unresolved,
    }
