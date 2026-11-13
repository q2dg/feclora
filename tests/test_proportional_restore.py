import unittest

from feclora.storage.proportional_restore import (
    ProportionalRestoreError,
    preview_proportional_gpt_restore,
)


class ProportionalRestorePreviewTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "source_size_bytes": 2 * 1024 * 1024 * 1024,
            "sector_size": 512,
            "partition_table_type": "gpt",
            "disk_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "first_usable_lba": 34,
            "last_usable_lba": 4194270,
            "partitions": (
                {"node": "/dev/src1", "start": 2048, "size": 204800,
                 "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
                {"node": "/dev/src2", "start": 206848, "size": 3000000,
                 "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"},
            ),
            "filesystem_types": {"/dev/src1": "vfat", "/dev/src2": "ext4"},
        }
        self.target = {
            "target_size_bytes": 1024 * 1024 * 1024,
            "sector_size": 512,
            "partition_table_type": "gpt",
            "existing_partitions": ({"path": "/dev/dst1", "filesystem_type": "ext4"},),
            "model": "Target model", "serial": "TARGET-123", "wwn": None,
            "write_authorized": False,
        }

    def preview(self, *, source=None, target=None, probe=None, identity=None):
        return preview_proportional_gpt_restore(
            "/dev/source", "/dev/target",
            source_inspector=lambda path, **kwargs: source or self.source,
            target_inspector=lambda path, **kwargs: target or self.target,
            device_identity=identity or (lambda path: (8, 0) if path.endswith("source") else (8, 16)),
            minimum_probe=probe or (lambda path, **kwargs: 200000000),
        )

    def test_builds_combined_read_only_plan_and_reports_target_identity(self):
        result = self.preview()
        self.assertEqual(result["source_size_bytes"], self.source["source_size_bytes"])
        self.assertEqual(result["target_size_bytes"], self.target["target_size_bytes"])
        self.assertEqual(result["target_identity"]["serial"], "TARGET-123")
        self.assertEqual(result["source_gpt_disk_guid"], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(result["source_gpt_first_usable_lba"], 34)
        self.assertEqual(result["source_gpt_last_usable_lba"], 4194270)
        self.assertEqual(len(result["partitions"]), 2)
        self.assertTrue(result["destructive_confirmation_required"])
        self.assertFalse(result["write_authorized"])
        self.assertEqual(result["existing_target_partitions"], self.target["existing_partitions"])

    def test_refuses_same_physical_device_even_through_different_paths(self):
        with self.assertRaisesRegex(ProportionalRestoreError, "same physical"):
            self.preview(identity=lambda path: (8, 0))

    def test_refuses_equal_or_larger_target(self):
        target = dict(self.target, target_size_bytes=self.source["source_size_bytes"])
        with self.assertRaisesRegex(ProportionalRestoreError, "strictly smaller"):
            self.preview(target=target)

    def test_refuses_sector_size_mismatch(self):
        target = dict(self.target, sector_size=4096)
        with self.assertRaisesRegex(ProportionalRestoreError, "sector sizes differ"):
            self.preview(target=target)

    def test_refuses_unverified_write_boundary(self):
        target = dict(self.target, write_authorized=True)
        with self.assertRaisesRegex(ProportionalRestoreError, "no-write guarantee"):
            self.preview(target=target)

    def test_fails_closed_when_filesystem_minimum_probe_fails(self):
        def fail_probe(path, **kwargs):
            raise RuntimeError("cannot safely probe")
        with self.assertRaisesRegex(ProportionalRestoreError, "cannot construct"):
            self.preview(probe=fail_probe)


if __name__ == "__main__":
    unittest.main()
