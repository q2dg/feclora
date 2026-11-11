import unittest

from feclora.storage.capture_plan import CapturePlanError, plan_storage_capture


def base_inventory(device, **extra):
    return {
        "devices": [device],
        "storage_graph": {"status": "available", "nodes": [], "edges": []},
        **extra,
    }


class StorageCapturePlanTests(unittest.TestCase):
    def test_disk_capture_includes_partition_descendants(self):
        inventory = base_inventory({
            "path": "/dev/sda", "type": "disk", "size_bytes": 1000,
            "children": [{"path": "/dev/sda1", "type": "part", "filesystem": "ext4", "children": []}],
        })
        plan = plan_storage_capture(inventory, "/dev/sda", "disk")
        self.assertEqual(plan["capture_scope"], "whole_disk_bytes")
        self.assertTrue(plan["eligible_for_layer_aware_capture"])

    def test_luks_partition_is_explicitly_raw_encrypted_container(self):
        inventory = base_inventory({
            "path": "/dev/sda2", "type": "part", "filesystem": "crypto_LUKS",
            "volume_features": ["luks", "luks_container"], "children": [],
        }, luks_metadata={"containers": [{"device": "/dev/sda2", "uuid": "luks-uuid"}]})
        plan = plan_storage_capture(inventory, "/dev/sda2", "partition")
        self.assertEqual(plan["capture_scope"], "encrypted_container_bytes")
        self.assertEqual(plan["manifest_storage"]["source_layer"], "luks2_container")
        self.assertEqual(plan["manifest_storage"]["luks_uuid"], "luks-uuid")
        self.assertIn("luks2_container", plan["storage_layers"])
        self.assertEqual(plan["dependencies"][0]["uuid"], "luks-uuid")

    def test_whole_disk_reports_nested_luks_and_lvm_layers(self):
        inventory = base_inventory({
            "path": "/dev/sda", "type": "disk", "children": [
                {"path": "/dev/sda1", "type": "part", "filesystem": "crypto_LUKS",
                 "volume_features": ["luks_container"], "children": []},
                {"path": "/dev/sda2", "type": "part", "filesystem": "LVM2_member",
                 "volume_features": ["lvm", "lvm_pv"], "children": []},
            ],
        }, luks_metadata={"containers": [{"device": "/dev/sda1", "uuid": "luks-1"}]},
           volume_topology={"pvs": [{"pv_name": "/dev/sda2", "vg_name": "vg0"}],
                            "volume_groups": []})
        plan = plan_storage_capture(inventory, "/dev/sda", "disk")
        self.assertEqual(plan["capture_scope"], "whole_disk_bytes")
        self.assertIn("luks2_container", plan["storage_layers"])
        self.assertIn("lvm_physical_volume", plan["storage_layers"])
        self.assertTrue(any(item.get("device_path") == "/dev/sda1"
                            for item in plan["dependencies"]))

    def test_luks_container_feature_without_filesystem_signature_is_raw_encrypted_scope(self):
        inventory = base_inventory({
            "path": "/dev/sda3", "type": "part",
            "volume_features": ["luks_container"], "children": [],
        })
        plan = plan_storage_capture(inventory, "/dev/sda3", "partition")
        self.assertEqual(plan["capture_scope"], "encrypted_container_bytes")
        self.assertIn("luks2_container", plan["storage_layers"])
        self.assertTrue(plan["dependencies"][0]["included_in_source_bytes"])

    def test_open_crypt_mapping_is_not_misrepresented_as_luks_header_backup(self):
        inventory = base_inventory({
            "path": "/dev/mapper/secure", "type": "crypt", "filesystem": "ext4",
            "volume_features": ["encrypted", "crypt_mapping"], "children": [],
        })
        plan = plan_storage_capture(inventory, "/dev/mapper/secure", "logical_volume")
        self.assertEqual(plan["capture_scope"], "decrypted_mapping_bytes")
        self.assertTrue(any("not its LUKS header" in warning for warning in plan["warnings"]))

    def test_multi_device_btrfs_member_cannot_be_captured_as_standalone_partition(self):
        inventory = base_inventory({
            "path": "/dev/sda2", "type": "part", "filesystem": "btrfs", "children": [],
        }, btrfs_topology={"filesystems": [{
            "uuid": "btrfs-uuid", "total_devices": 2,
            "devices": [{"path": "/dev/sda2"}, {"path": "/dev/sdb2"}],
        }]})
        plan = plan_storage_capture(inventory, "/dev/sda2", "partition")
        self.assertFalse(plan["eligible_for_layer_aware_capture"])
        self.assertTrue(any("omits one or more devices" in item for item in plan["blockers"]))

    def test_whole_disk_btrfs_is_complete_only_when_all_members_are_descendants(self):
        inventory = base_inventory({
            "path": "/dev/sda", "type": "disk", "children": [
                {"path": "/dev/sda2", "type": "part", "filesystem": "btrfs", "children": []}
            ],
        }, btrfs_topology={"filesystems": [{
            "uuid": "btrfs-uuid", "total_devices": 2,
            "devices": [{"path": "/dev/sda2"}, {"path": "/dev/sdb2"}],
        }]})
        plan = plan_storage_capture(inventory, "/dev/sda", "disk")
        self.assertFalse(plan["eligible_for_layer_aware_capture"])

    def test_mounted_source_blocks_consistent_capture_plan(self):
        inventory = base_inventory({
            "path": "/dev/sda1", "type": "part", "filesystem": "xfs",
            "mountpoints": ["/mnt/data"], "children": [],
        })
        plan = plan_storage_capture(inventory, "/dev/sda1", "partition")
        self.assertFalse(plan["eligible_for_layer_aware_capture"])
        self.assertTrue(any("mounted or in use" in item for item in plan["blockers"]))

    def test_requires_exact_unique_source(self):
        with self.assertRaises(CapturePlanError):
            plan_storage_capture({"devices": []}, "/dev/sda", "disk")
        with self.assertRaises(CapturePlanError):
            plan_storage_capture({"devices": [
                {"path": "/dev/sda", "type": "disk"},
                {"path": "/dev/sda", "type": "disk"},
            ]}, "/dev/sda", "disk")

    def test_lvm_logical_volume_reports_missing_volume_group_metadata(self):
        inventory = base_inventory({
            "path": "/dev/mapper/vg-data", "type": "lvm", "filesystem": "xfs",
            "major_minor": "253:4", "children": [],
        }, storage_graph={
            "status": "available",
            "nodes": [{"id": "lvm-lv:lv-1", "kind": "lvm_logical_volume", "name": "data", "uuid": "lv-1"},
                      {"id": "lvm-vg:vg0", "kind": "lvm_volume_group", "name": "vg0"}],
            "edges": [
                {"source": "lvm-lv:lv-1", "target": "device:/dev/mapper/vg-data",
                 "relation": "maps_to_block_device"},
                {"source": "lvm-vg:vg0", "target": "lvm-lv:lv-1",
                 "relation": "contains_lv"},
            ],
        })
        plan = plan_storage_capture(inventory, "/dev/mapper/vg-data", "logical_volume")
        self.assertIn("lvm_logical_volume", plan["storage_layers"])
        self.assertEqual(plan["manifest_storage"]["source_layer"], "lvm_logical_volume")
        self.assertEqual(plan["manifest_storage"]["lvm_vg_name"], "vg0")
        self.assertEqual(plan["manifest_storage"]["lvm_lv_uuid"], "lv-1")
        self.assertFalse(plan["dependencies"][0]["included_in_source_bytes"])

    def test_disk_capture_blocks_when_a_child_partition_is_mounted(self):
        inventory = base_inventory({
            "path": "/dev/sda", "type": "disk", "children": [
                {"path": "/dev/sda1", "type": "part", "mountpoints": ["/"], "children": []}
            ],
        })
        plan = plan_storage_capture(inventory, "/dev/sda", "disk")
        self.assertFalse(plan["eligible_for_layer_aware_capture"])
        self.assertTrue(any("descendants is mounted" in item for item in plan["blockers"]))

    def test_rejects_unknown_image_type(self):
        with self.assertRaises(CapturePlanError):
            plan_storage_capture({"devices": []}, "/dev/sda", "volume")


if __name__ == "__main__":
    unittest.main()
