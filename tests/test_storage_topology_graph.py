import unittest

from feclora.storage.topology_graph import build_storage_graph


class StorageTopologyGraphTests(unittest.TestCase):
    def test_joins_disk_luks_pv_vg_lv_and_filesystem_layers(self):
        inventory = {
            "devices": [
                {"path": "/dev/sda", "type": "disk", "children": [
                    {"path": "/dev/sda2", "type": "part", "filesystem": "crypto_LUKS",
                     "volume_features": ["luks", "luks_container"], "children": [
                        {"path": "/dev/mapper/cryptroot", "type": "crypt",
                         "filesystem": "LVM2_member", "volume_features": ["encrypted", "crypt_mapping", "lvm", "lvm_pv"],
                         "children": [
                            {"path": "/dev/mapper/root", "type": "lvm", "filesystem": "ext4", "major_minor": "253:0",
                             "uuid": "fs-root", "volume_features": ["lvm", "lvm_lv"], "children": []}
                         ]}
                    ]}
                ]}
            ],
            "luks_metadata": {"containers": [{"device": "/dev/sda2", "uuid": "luks-uuid",
                "cipher": "aes-xts-plain64", "keyslot_count": 1}]},
            "volume_topology": {
                "pvs": [{"pv_name": "/dev/mapper/cryptroot", "pv_uuid": "pv-uuid",
                         "vg_name": "fedora", "pv_size": "1000", "pv_free": "200"}],
                "volume_groups": [{"name": "fedora", "uuid": "vg-uuid", "status": "healthy",
                    "logical_volumes": [{"path": "/dev/fedora/root", "name": "root",
                        "uuid": "lv-uuid", "size_bytes": 800, "segment_type": "linear", "major_minor": "253:0",
                        "devices": "/dev/mapper/cryptroot(0)", "thin_provisioned": False,
                        "snapshot": False, "hidden": False}]}],
            },
            "btrfs_topology": {"filesystems": []},
            "btrfs_subvolumes": {"mounts": []},
            "stratis_topology": {"status": "available", "pools": []},
        }
        graph = build_storage_graph(inventory)
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertIn(("device:/dev/sda", "device:/dev/sda2", "contains"), relations)
        self.assertIn(("device:/dev/sda2", "luks:luks-uuid", "contains_encrypted_container"), relations)
        self.assertIn(("device:/dev/sda2", "device:/dev/mapper/cryptroot", "opened_as_mapping"), relations)
        self.assertIn(("device:/dev/mapper/cryptroot", "lvm-pv:pv-uuid", "contains_pv"), relations)
        self.assertIn(("lvm-pv:pv-uuid", "lvm-vg:fedora", "member_of"), relations)
        self.assertIn(("lvm-vg:fedora", "lvm-lv:lv-uuid", "contains_lv"), relations)
        self.assertIn(("lvm-lv:lv-uuid", "lvm-pv:pv-uuid", "allocated_on"), relations)
        self.assertTrue(any(n["id"] == "filesystem:fs-root" for n in graph["nodes"]))
        self.assertIn(("lvm-lv:lv-uuid", "device:/dev/mapper/root", "maps_to_block_device"), relations)
        self.assertIn(("lvm-lv:lv-uuid", "filesystem:fs-root", "hosts_filesystem"), relations)
        self.assertIn(("lvm-lv:lv-uuid", "lvm-pv:pv-uuid", "allocated_on"), relations)

    def test_reports_unmatched_device_paths_instead_of_guessing_aliases(self):
        graph = build_storage_graph({
            "devices": [{"path": "/dev/sda", "type": "disk", "children": []}],
            "volume_topology": {"pvs": [{"pv_name": "/dev/mapper/missing", "vg_name": "vg"}],
                "volume_groups": [], "lvs": []},
            "btrfs_topology": {"filesystems": [{"uuid": "btrfs-id", "devices": [
                {"path": "/dev/sdb1"}]}]},
        })
        unresolved = {(item["layer"], item["path"]) for item in graph["unresolved"]}
        self.assertIn(("lvm_pv", "/dev/mapper/missing"), unresolved)
        self.assertIn(("btrfs_member", "/dev/sdb1"), unresolved)

    def test_btrfs_multi_device_filesystem_links_all_members(self):
        graph = build_storage_graph({
            "devices": [{"path": "/dev/sda1", "type": "part", "children": []},
                        {"path": "/dev/sdb1", "type": "part", "children": []}],
            "btrfs_topology": {"filesystems": [{"uuid": "btrfs-id", "label": "data",
                "total_devices": 2, "devices": [{"path": "/dev/sda1"}, {"path": "/dev/sdb1"}]}]},
        })
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertIn(("btrfs:btrfs-id", "device:/dev/sda1", "spans_device"), relations)
        self.assertIn(("btrfs:btrfs-id", "device:/dev/sdb1", "spans_device"), relations)

    def test_received_subvolume_and_snapshot_provenance_are_preserved(self):
        graph = build_storage_graph({
            "devices": [],
            "btrfs_topology": {"status": "available", "filesystems": [{"uuid": "fs-uuid", "devices": []}]},
            "btrfs_subvolumes": {"mounts": [{"mountpoint": "/mnt/data", "uuid": "fs-uuid", "subvolumes": [
                {"id": 256, "uuid": "subvol-1", "path": "@", "kind": "subvolume",
                 "parent_uuid": None, "received_uuid": None},
                {"id": 257, "uuid": "subvol-2", "path": "@snap", "kind": "snapshot",
                 "parent_uuid": "subvol-1", "received_uuid": None},
            ]}]},
        })
        by_uuid = {n.get("uuid"): n for n in graph["nodes"] if n["kind"] == "btrfs_subvolume"}
        self.assertEqual(by_uuid["subvol-2"]["parent_uuid"], "subvol-1")
        self.assertEqual(by_uuid["subvol-1"]["kind"], "btrfs_subvolume")
        self.assertEqual(by_uuid["subvol-1"]["subvolume_kind"], "subvolume")
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertIn(("btrfs-subvolume:subvol-2", "btrfs-subvolume:subvol-1", "snapshot_of"), relations)
        self.assertIn(("btrfs:fs-uuid", "btrfs-subvolume:subvol-1", "contains_subvolume"), relations)

    def test_attaches_btrfs_allocation_profiles_to_filesystem_node(self):
        graph = build_storage_graph({
            "devices": [{"path": "/dev/sda1", "type": "part", "filesystem": "btrfs", "uuid": "btrfs-uuid", "children": []}],
            "btrfs_topology": {"filesystems": [{
                "uuid": "btrfs-uuid", "total_devices": 1,
                "devices": [{"devid": 1, "size_bytes": 1000, "path": "/dev/sda1"}],
            }]},
            "btrfs_subvolumes": {"mounts": [{
                "uuid": "btrfs-uuid", "mountpoint": "/mnt/data",
                "allocation_profiles": [
                    {"type": "data", "profile": "single", "known_profile": True},
                    {"type": "metadata", "profile": "dup", "known_profile": True},
                ],
                "subvolumes": [],
            }]},
        })
        filesystem = next(node for node in graph["nodes"] if node["id"] == "btrfs:btrfs-uuid")
        self.assertEqual(filesystem["allocation_profile_inventory"], "available")
        self.assertEqual(filesystem["allocation_profiles"][1]["profile"], "dup")
        self.assertFalse(filesystem["has_unknown_allocation_profile"])

    def test_joins_stratis_pool_filesystem_mapper_and_backing_device(self):
        graph = build_storage_graph({
            "devices": [{"path": "/dev/dm-3", "type": "lvm", "children": []},
                        {"path": "/dev/sda1", "type": "part", "children": []}],
            "stratis_topology": {"status": "available", "pools": [{
                "name": "poolA", "filesystems": [{
                    "name": "fs1", "device": "/dev/stratis/poolA/fs1",
                    "mapper_device": "/dev/dm-3",
                    "backing_device_paths": ["/dev/sda1"],
                }]
            }]},
        })
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertIn(("stratis-pool:poolA", "stratis-filesystem:poolA/fs1", "contains_filesystem"), relations)
        self.assertIn(("stratis-filesystem:poolA/fs1", "device:/dev/dm-3", "maps_to_block_device"), relations)
        self.assertIn(("stratis-filesystem:poolA/fs1", "device:/dev/sda1", "backed_by"), relations)

    def test_reports_incomplete_sources_and_unmatched_lvm_lv_paths(self):
        graph = build_storage_graph({
            "devices": [{"path": "/dev/mapper/vg-root", "type": "lvm", "major_minor": "253:0", "children": []}],
            "volume_topology": {"status": "available", "pvs": [], "volume_groups": [{
                "name": "vg", "logical_volumes": [{"path": "/dev/vg/root", "name": "root"}]
            }]},
            "luks_metadata": {"status": "permission_required", "containers": []},
        })
        self.assertEqual(graph["status"], "partial")
        self.assertIn({"layer": "lvm_lv", "path": "/dev/vg/root",
                       "reason": "lv_path_and_device_identity_not_matched"}, graph["unresolved"])
        self.assertIn({"source": "luks_metadata", "status": "permission_required"},
                      graph["source_statuses"])


    def test_exact_lv_path_with_conflicting_major_minor_is_unresolved(self):
        graph = build_storage_graph({
            "devices": [{
                "path": "/dev/mapper/vg-root", "type": "lvm",
                "major_minor": "253:7", "filesystem": "ext4",
                "uuid": "root-fs", "children": [],
            }],
            "volume_topology": {"status": "available", "pvs": [], "volume_groups": [{
                "name": "vg", "logical_volumes": [{
                    "path": "/dev/mapper/vg-root", "name": "root",
                    "uuid": "lv-root", "major_minor": "253:8",
                }]
            }]},
        })
        self.assertIn({"layer": "lvm_lv", "path": "/dev/mapper/vg-root",
                       "reason": "device_path_and_major_minor_conflict"}, graph["unresolved"])
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertFalse(any(source == "lvm-lv:lv-root" and relation == "maps_to_block_device"
                             for source, target, relation in relations))
        self.assertEqual(graph["status"], "partial")

    def test_exact_lv_path_remains_usable_when_major_minor_is_unavailable(self):
        graph = build_storage_graph({
            "devices": [{"path": "/dev/mapper/vg-root", "type": "lvm", "children": []}],
            "volume_topology": {"status": "available", "pvs": [], "volume_groups": [{
                "name": "vg", "logical_volumes": [{
                    "path": "/dev/mapper/vg-root", "name": "root",
                    "major_minor": "253:8",
                }]
            }]},
        })
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertIn(("lvm-lv:/dev/mapper/vg-root", "device:/dev/mapper/vg-root", "maps_to_block_device"), relations)

    def test_major_minor_match_must_be_unique(self):
        graph = build_storage_graph({
            "devices": [
                {"path": "/dev/dm-0", "type": "lvm", "major_minor": "253:4",
                 "filesystem": "xfs", "uuid": "fs-a", "children": []},
                {"path": "/dev/mapper/vg-data", "type": "lvm", "major_minor": "253:4",
                 "filesystem": "xfs", "uuid": "fs-b", "children": []},
            ],
            "volume_topology": {"status": "available", "pvs": [], "volume_groups": [{
                "name": "vg", "logical_volumes": [{"path": "/dev/vg/data",
                    "name": "data", "major_minor": "253:4"}]
            }]},
        })
        self.assertIn({"layer": "lvm_lv", "path": "/dev/vg/data",
                       "reason": "device_major_minor_is_ambiguous"}, graph["unresolved"])
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertFalse(any(source == "lvm-lv:vg/data" and relation == "maps_to_block_device"
                             for source, target, relation in relations))
