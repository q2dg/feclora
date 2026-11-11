import unittest

from feclora.storage.image_manifest import ImageManifest
from feclora.storage.profile_executor import preflight_logical_volume_restore
from feclora.storage.restore_profile import RestoreProfileError


def make_manifest():
    return ImageManifest.from_dict({
        "schema_version": 1,
        "image_id": "root-lv",
        "image_type": "logical_volume",
        "source_size_bytes": 8000,
        "logical_sector_size": 512,
        "partition_table": "none",
        "artifacts": [{
            "filename": "root-lv.img",
            "role": "logical-volume-image",
            "format": "raw",
            "compression": "none",
            "size_bytes": 8000,
            "sha256": "a" * 64,
        }],
        "storage": {
            "schema_version": 1,
            "capture_scope": "logical_volume_bytes",
            "source_layer": "lvm_logical_volume",
            "lvm_vg_name": "source-vg",
            "lvm_vg_uuid": "source-vg-uuid",
            "lvm_lv_name": "root",
            "lvm_lv_uuid": "source-lv-uuid",
            "dependencies": [{
                "kind": "lvm_volume_group",
                "identity": "source-vg-uuid",
                "included_in_source_bytes": False,
            }],
        },
    })


def make_inventory(*, size=10000, mounted=None, vg_status="healthy",
                   major_minor="253:4", thin=False, pool_data="20",
                   pool_metadata="10"):
    target = {
        "path": "/dev/target/root",
        "name": "root",
        "uuid": "target-lv-uuid",
        "size_bytes": size,
        "major_minor": major_minor,
        "segment_type": "thin" if thin else "linear",
        "thin_provisioned": thin,
        "pool": "pool0" if thin else None,
        "snapshot": False,
        "origin": None,
        "hidden": False,
        "health": None,
        "data_percent": None,
        "metadata_percent": None,
    }
    lvs = [target]
    if thin:
        lvs.append({
            "path": "/dev/target/pool0",
            "name": "pool0",
            "size_bytes": 20000,
            "segment_type": "thin-pool",
            "thin_provisioned": True,
            "pool": None,
            "snapshot": False,
            "origin": None,
            "hidden": False,
            "health": None,
            "data_percent": pool_data,
            "metadata_percent": pool_metadata,
        })
    return {
        "volume_topology": {
            "status": "available",
            "volume_groups": [{
                "name": "target-vg",
                "uuid": "target-vg-uuid",
                "status": vg_status,
                "missing_pv_count": 0 if vg_status == "healthy" else 1,
                "pv_count_reported": 1,
                "pv_members": [{"path": "/dev/sda2", "uuid": "pv-1", "missing": False}],
                "logical_volumes": lvs,
            }],
        },
        "devices": [{
            "path": "/dev/target/root",
            "type": "lvm",
            "major_minor": major_minor,
            "logical_sector_size": 512,
            "read_only": False,
            "mountpoints": mounted or [],
            "children": [],
        }],
    }


class LogicalVolumeRestorePreflightTests(unittest.TestCase):
    def test_accepts_healthy_active_unmounted_lv_with_enough_capacity(self):
        result = preflight_logical_volume_restore(
            make_manifest(), make_inventory(), "/dev/target/root"
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["target_vg"], "target-vg")
        self.assertEqual(result["target_lv"], "root")
        self.assertFalse(result["writes_performed"])
        self.assertFalse(result["activation_performed"])

    def test_rejects_degraded_vg(self):
        with self.assertRaisesRegex(RestoreProfileError, "degraded"):
            preflight_logical_volume_restore(
                make_manifest(), make_inventory(vg_status="degraded"), "/dev/target/root"
            )

    def test_rejects_target_smaller_than_image(self):
        with self.assertRaisesRegex(RestoreProfileError, "smaller"):
            preflight_logical_volume_restore(
                make_manifest(), make_inventory(size=7999), "/dev/target/root"
            )

    def test_rejects_mounted_target(self):
        with self.assertRaisesRegex(RestoreProfileError, "mounted or in use"):
            preflight_logical_volume_restore(
                make_manifest(), make_inventory(mounted=["/mnt/root"]), "/dev/target/root"
            )

    def test_resolves_lsblk_mapper_alias_by_unique_major_minor(self):
        inventory = make_inventory()
        inventory["devices"][0]["path"] = "/dev/mapper/target-root"
        result = preflight_logical_volume_restore(
            make_manifest(), inventory, "/dev/target/root"
        )
        self.assertEqual(result["status"], "ready")

    def test_rejects_logical_sector_size_mismatch(self):
        inventory = make_inventory()
        inventory["devices"][0]["logical_sector_size"] = 4096
        with self.assertRaisesRegex(RestoreProfileError, "sector size differs"):
            preflight_logical_volume_restore(make_manifest(), inventory, "/dev/target/root")

    def test_rejects_mounted_child_device(self):
        inventory = make_inventory()
        inventory["devices"][0]["children"] = [{
            "path": "/dev/target/root1",
            "type": "part",
            "major_minor": "253:5",
            "logical_sector_size": 512,
            "read_only": False,
            "mountpoints": ["/mnt/child"],
            "children": [],
        }]
        with self.assertRaisesRegex(RestoreProfileError, "child devices"):
            preflight_logical_volume_restore(make_manifest(), inventory, "/dev/target/root")

    def test_rejects_kernel_identity_mismatch(self):
        inventory = make_inventory()
        inventory["devices"][0]["major_minor"] = "253:5"
        with self.assertRaisesRegex(RestoreProfileError, "identities disagree"):
            preflight_logical_volume_restore(
                make_manifest(), inventory, "/dev/target/root"
            )

    def test_rejects_inactive_lv_without_kernel_identity(self):
        inventory = make_inventory(major_minor=None)
        inventory["devices"][0]["major_minor"] = None
        with self.assertRaisesRegex(RestoreProfileError, "not active"):
            preflight_logical_volume_restore(make_manifest(), inventory, "/dev/target/root")

    def test_validates_thin_pool_health_and_capacity_indicators(self):
        result = preflight_logical_volume_restore(
            make_manifest(), make_inventory(thin=True), "/dev/target/root"
        )
        self.assertTrue(result["thin_provisioned"])
        self.assertEqual(result["thin_pool"], "pool0")
        self.assertTrue(any("does not reserve extents" in item for item in result["warnings"]))

        with self.assertRaisesRegex(RestoreProfileError, "exhausted"):
            preflight_logical_volume_restore(
                make_manifest(), make_inventory(thin=True, pool_data="100"), "/dev/target/root"
            )
        with self.assertRaisesRegex(RestoreProfileError, "unknown"):
            preflight_logical_volume_restore(
                make_manifest(), make_inventory(thin=True, pool_metadata=None), "/dev/target/root"
            )

    def test_rejects_snapshot_origin_and_lv_with_dependent_snapshots(self):
        inventory = make_inventory()
        inventory["volume_topology"]["volume_groups"][0]["logical_volumes"][0]["snapshot"] = True
        with self.assertRaisesRegex(RestoreProfileError, "snapshot LVs"):
            preflight_logical_volume_restore(make_manifest(), inventory, "/dev/target/root")

        inventory = make_inventory()
        inventory["volume_topology"]["volume_groups"][0]["logical_volumes"].append({
            "name": "root-snap", "origin": "root", "snapshot": True,
        })
        with self.assertRaisesRegex(RestoreProfileError, "dependent snapshots"):
            preflight_logical_volume_restore(make_manifest(), inventory, "/dev/target/root")


if __name__ == "__main__":
    unittest.main()
