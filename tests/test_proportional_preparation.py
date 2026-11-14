import os
import tempfile
import unittest
from unittest.mock import patch

from feclora.storage.partition_layout import PlannedPartition
from feclora.storage.proportional_staging import StagedRawDiskImage
from feclora.storage.proportional_preparation import (
    ProportionalStagedPreparationError,
    prepare_proportional_staged_image,
)


TYPE_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"
PARTUUID = "11111111-2222-3333-4444-555555555555"


class ProportionalStagedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "disk.raw")
        with open(self.path, "wb") as stream:
            stream.write(b"\0" * (20 * 1024 * 1024))
        self.staged = StagedRawDiskImage(self.path, os.path.getsize(self.path), "a" * 64)
        self.source_partition_sectors = 20480
        self.source_gpt = {
            "sector_size": 512,
            "partitions": [{
                "unique_guid": PARTUUID,
                "first_lba": 2048,
                "last_lba": 2048 + self.source_partition_sectors - 1,
                "type_guid": TYPE_GUID,
            }],
        }
        self.plan = PlannedPartition(
            node="/dev/source1", type_guid=TYPE_GUID, partuuid=PARTUUID,
            name=None, start_sector=2048, size_sectors=10240,
            minimum_size_bytes=1024 * 1024,
        )

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, filesystem):
        return prepare_proportional_staged_image(
            self.staged,
            target_size_bytes=16 * 1024 * 1024,
            sector_size=512,
            planned_partitions=(self.plan,),
            filesystem_types={"/dev/source1": filesystem},
            executables={"ntfsresize": "/sbin/ntfsresize"},
            runner=lambda *_args, **_kwargs: None,
            which=lambda _name: None,
            block_device_validator=lambda _path: True,
            safety_check=lambda _path: None,
            effective_uid=lambda: 0,
        )

    @patch("feclora.storage.proportional_preparation.apply_gpt_rewrite_to_staged_image")
    @patch("feclora.storage.proportional_preparation.shrink_staged_ext_filesystem")
    @patch("feclora.storage.proportional_preparation.inspect_gpt_binary")
    def test_routes_ext_shrink_then_rewrites_gpt(self, inspect, shrink, rewrite):
        inspect.return_value = self.source_gpt
        shrink.return_value = self.staged
        rewrite.return_value = StagedRawDiskImage(self.path, 16 * 1024 * 1024, "b" * 64)
        result = self.prepare("ext4")
        self.assertEqual(result.size_bytes, 16 * 1024 * 1024)
        kwargs = shrink.call_args.kwargs
        self.assertEqual(kwargs["partition_start_sector"], 2048)
        self.assertEqual(kwargs["source_partition_size_sectors"], self.source_partition_sectors)
        self.assertEqual(kwargs["target_partition_size_bytes"], 5 * 1024 * 1024)
        self.assertEqual(kwargs["target_filesystem_size_bytes"] % 65536, 0)
        rewrite.assert_called_once()

    @patch("feclora.storage.proportional_preparation.apply_gpt_rewrite_to_staged_image")
    @patch("feclora.storage.proportional_preparation.shrink_staged_ntfs_filesystem")
    @patch("feclora.storage.proportional_preparation.inspect_gpt_binary")
    def test_routes_ntfs_shrink_then_rewrites_gpt(self, inspect, shrink, rewrite):
        inspect.return_value = self.source_gpt
        shrink.return_value = self.staged
        rewrite.return_value = self.staged
        self.prepare("ntfs")
        self.assertEqual(
            shrink.call_args.kwargs["target_filesystem_size_bytes"],
            5 * 1024 * 1024,
        )
        rewrite.assert_called_once()

    @patch("feclora.storage.proportional_preparation.apply_gpt_rewrite_to_staged_image")
    @patch("feclora.storage.proportional_preparation.shrink_staged_ext_filesystem")
    @patch("feclora.storage.proportional_preparation.inspect_gpt_binary")
    def test_does_not_shrink_when_partition_already_fits(self, inspect, shrink, rewrite):
        inspect.return_value = self.source_gpt
        unchanged = PlannedPartition(
            node="/dev/source1", type_guid=TYPE_GUID, partuuid=PARTUUID,
            name=None, start_sector=2048, size_sectors=self.source_partition_sectors,
            minimum_size_bytes=1024 * 1024,
        )
        rewrite.return_value = self.staged
        result = prepare_proportional_staged_image(
            self.staged, target_size_bytes=16 * 1024 * 1024,
            sector_size=512, planned_partitions=(unchanged,),
            filesystem_types={"/dev/source1": "ext4"},
        )
        self.assertEqual(result, self.staged)
        shrink.assert_not_called()
        rewrite.assert_called_once()

    @patch("feclora.storage.proportional_preparation.inspect_gpt_binary")
    def test_rejects_unsupported_filesystem_before_gpt_rewrite(self, inspect):
        inspect.return_value = self.source_gpt
        with patch("feclora.storage.proportional_preparation.apply_gpt_rewrite_to_staged_image") as rewrite:
            with self.assertRaisesRegex(ProportionalStagedPreparationError, "no staged shrink executor"):
                self.prepare("xfs")
            rewrite.assert_not_called()

    @patch("feclora.storage.proportional_preparation.inspect_gpt_binary")
    def test_rejects_plan_that_changes_partition_start(self, inspect):
        inspect.return_value = self.source_gpt
        wrong = PlannedPartition(
            node="/dev/source1", type_guid=TYPE_GUID, partuuid=PARTUUID,
            name=None, start_sector=4096, size_sectors=8192,
            minimum_size_bytes=1024 * 1024,
        )
        with self.assertRaisesRegex(ProportionalStagedPreparationError, "start geometry"):
            prepare_proportional_staged_image(
                self.staged, target_size_bytes=16 * 1024 * 1024,
                sector_size=512, planned_partitions=(wrong,),
                filesystem_types={"/dev/source1": "ext4"},
            )


if __name__ == "__main__":
    unittest.main()
