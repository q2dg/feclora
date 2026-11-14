import unittest
from unittest.mock import patch
from types import SimpleNamespace
import stat
import os

from feclora.storage.proportional_staging import StagedRawDiskImage
from feclora.storage.proportional_restore_workflow import (
    ProportionalRestoreWorkflowError,
    prepare_from_offline_source_disk,
    require_distinct_block_devices,
)


class ProportionalRestoreWorkflowTests(unittest.TestCase):
    def test_rejects_source_and_destination_aliasing_same_block_device(self):
        devices = {
            "/dev/disk/by-id/source": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=2049),
            "/dev/sda": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=2049),
        }
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "same physical"):
            require_distinct_block_devices(
                "/dev/disk/by-id/source", "/dev/sda",
                stat_device=devices.__getitem__,
            )

    def test_accepts_distinct_block_device_identities(self):
        devices = {
            "/dev/sda": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=2048),
            "/dev/sdb": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=2064),
        }
        self.assertEqual(
            require_distinct_block_devices("/dev/sda", "/dev/sdb", stat_device=devices.__getitem__),
            (2048, 2064),
        )

    def test_rejects_stale_inventory_major_minor_identity(self):
        devices = {
            "/dev/sda": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0)),
            "/dev/sdb": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 16)),
        }
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "source no longer matches"):
            require_distinct_block_devices(
                "/dev/sda", "/dev/sdb",
                source_major_minor="8:1", target_major_minor="8:16",
                stat_device=devices.__getitem__,
            )

    def test_rejects_regular_file_as_destination(self):
        devices = {
            "/dev/sda": SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=2048),
            "/dev/not-a-device": SimpleNamespace(st_mode=stat.S_IFREG, st_rdev=0),
        }
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "block devices"):
            require_distinct_block_devices(
                "/dev/sda", "/dev/not-a-device", stat_device=devices.__getitem__
            )

    def setUp(self):
        self.staged = StagedRawDiskImage("/private/stage/disk.raw", 4 * 1024 * 1024, "a" * 64)
        self.source = {
            "type": "disk",
            "path": "/dev/sda",
            "size_bytes": 4 * 1024 * 1024,
            "logical_sector_size": 512,
            "children": [{
                "type": "part",
                "path": "/dev/sda1",
                "partuuid": "11111111-2222-3333-4444-555555555555",
                "partition_type_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "filesystem": "ext4",
                "start_sector": 2048,
                "size_bytes": 1024 * 1024,
            }],
        }
        self.gpt = {
            "primary_backup_consistent": True,
            "first_usable_lba": 34,
            "last_usable_lba": 8158,
            "partitions": [{
                "unique_guid": "11111111-2222-3333-4444-555555555555",
                "type_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "first_lba": 2048,
                "last_lba": 4095,
                "attributes": 0,
                "name": "root",
            }],
        }

    @patch("feclora.storage.proportional_restore_workflow.prepare_proportional_staged_image",
           return_value=StagedRawDiskImage("/private/stage/prepared.raw", 2 * 1024 * 1024, "b" * 64))
    @patch("feclora.storage.proportional_restore_workflow.build_proportional_gpt_plan",
           return_value=("planned-partition",))
    @patch("feclora.storage.proportional_restore_workflow.inspect_gpt_binary")
    def test_matches_source_by_partuuid_and_prepares_only_staging(
        self, inspect, planner, prepare
    ):
        inspect.return_value = self.gpt
        result = prepare_from_offline_source_disk(
            self.staged, self.source, target_size_bytes=2 * 1024 * 1024, sector_size=512
        )
        self.assertEqual(result.size_bytes, 2 * 1024 * 1024)
        planner.assert_called_once()
        planned_input = planner.call_args.args[0]
        self.assertEqual(planned_input[0]["node"], "/dev/sda1")
        self.assertEqual(planned_input[0]["start"], 2048)
        self.assertEqual(planned_input[0]["size"], 2048)
        prepare.assert_called_once()
        self.assertIs(prepare.call_args.args[0], self.staged)

    @patch("feclora.storage.proportional_restore_workflow.inspect_gpt_binary")
    def test_rejects_source_with_different_capacity_before_planning(self, inspect):
        source = dict(self.source, size_bytes=2048 * 1024)
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "capacity"):
            prepare_from_offline_source_disk(
                self.staged, source, target_size_bytes=2 * 1024 * 1024, sector_size=512
            )
        inspect.assert_not_called()

    @patch("feclora.storage.proportional_restore_workflow.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True, "partitions": []})
    def test_rejects_missing_staged_gpt_partitions(self, _inspect):
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "no GPT partitions"):
            prepare_from_offline_source_disk(
                self.staged, self.source, target_size_bytes=2 * 1024 * 1024, sector_size=512
            )

    @patch("feclora.storage.proportional_restore_workflow.inspect_gpt_binary")
    def test_rejects_partition_start_or_capacity_mismatch(self, inspect):
        source = {
            **self.source,
            "children": [dict(self.source["children"][0], start_sector=2049)],
        }
        inspect.return_value = self.gpt
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "geometry differs"):
            prepare_from_offline_source_disk(
                self.staged, source, target_size_bytes=2 * 1024 * 1024, sector_size=512
            )

    @patch("feclora.storage.proportional_restore_workflow.inspect_gpt_binary")
    def test_rejects_mismatched_partition_type_guid(self, inspect):
        gpt = dict(self.gpt)
        gpt["partitions"] = [dict(self.gpt["partitions"][0], type_guid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")]
        inspect.return_value = gpt
        with self.assertRaisesRegex(ProportionalRestoreWorkflowError, "type GUID"):
            prepare_from_offline_source_disk(
                self.staged, self.source, target_size_bytes=2 * 1024 * 1024, sector_size=512
            )


if __name__ == "__main__":
    unittest.main()
