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
                            {"path": "/dev/mapper/root", "type": "lvm", "filesystem": "ext4",
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
                        "uuid": "lv-uuid", "size_bytes": 800, "segment_type": "linear",
                        "devices": "/dev/mapper/cryptroot(0)", "thin_provisioned": False,
                        "snapshot": False, "hidden": False}]}],
            },
            "btrfs_topology": {"filesystems": []},
            "btrfs_subvolumes": {"mounts": []},
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
        self.assertEqual(graph["unresolved"], [])

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
            "btrfs_subvolumes": {"mounts": [{"mountpoint": "/mnt/data", "subvolumes": [
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
