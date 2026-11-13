import unittest

from feclora.storage.partition_layout import (
    PartitionLayoutError,
    plan_proportional_gpt_layout,
)


class ProportionalGPTLayoutTests(unittest.TestCase):
    def setUp(self):
        self.partitions = [
            {"node": "/dev/source1", "start": 2048, "size": 2_000_000,
             "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "uuid": "AAAA", "name": "EFI"},
            {"node": "/dev/source2", "start": 2_100_000, "size": 6_000_000,
             "type": "0fc63daf-8483-4772-8e79-3d69d8477de4", "uuid": "BBBB", "name": "root"},
        ]

    def test_plans_aligned_layout_that_fits_and_preserves_identity(self):
        plan = plan_proportional_gpt_layout(
            self.partitions,
            source_size_bytes=8_500_000_000,
            target_size_bytes=5_000_000_000,
            sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 1024 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
        )
        self.assertEqual([item.partuuid for item in plan], ["AAAA", "BBBB"])
        self.assertEqual([item.name for item in plan], ["EFI", "root"])
        self.assertTrue(all(item.start_sector * 512 % (1024 * 1024) == 0 for item in plan))
        self.assertLessEqual(plan[-1].end_sector, 5_000_000_000 // 512 - 34)
        self.assertTrue(all(left.end_sector < right.start_sector for left, right in zip(plan, plan[1:])))
        self.assertEqual(plan[0].minimum_size_bytes, 2_000_000 * 512)

    def test_rejects_minimum_sizes_that_do_not_fit(self):
        with self.assertRaisesRegex(PartitionLayoutError, "do not fit"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_500_000_000,
                target_size_bytes=1_000_000_000,
                sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                     "/dev/source2": 600_000_000},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )

    def test_requires_minimum_for_every_partition(self):
        with self.assertRaisesRegex(PartitionLayoutError, "filesystem minimum"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000,
                sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )

    def test_rejects_overlap_and_unknown_partition_type(self):
        overlapping = [dict(item) for item in self.partitions]
        overlapping[1]["start"] = 1_500_000
        with self.assertRaisesRegex(PartitionLayoutError, "overlap"):
            plan_proportional_gpt_layout(
                overlapping, source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512, "/dev/source2": 1},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )
        unknown = [dict(item) for item in self.partitions]
        unknown[0].pop("type")
        with self.assertRaisesRegex(PartitionLayoutError, "valid GPT type GUID"):
            plan_proportional_gpt_layout(
                unknown, source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512, "/dev/source2": 1},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )


    def test_rejects_shrinking_non_ext_filesystem(self):
        with self.assertRaisesRegex(PartitionLayoutError, "only permits shrinking ext2/3/4"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000,
                sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 256 * 1024 * 1024,
                                     "/dev/source2": 1024 * 1024 * 1024},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )

    def test_never_grows_partitions_to_consume_target_free_space(self):
        plan = plan_proportional_gpt_layout(
            self.partitions,
            source_size_bytes=8_500_000_000,
            target_size_bytes=8_000_000_000,
            sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 6_000_000 * 512},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
        )
        self.assertLessEqual(plan[0].size_sectors, self.partitions[0]["size"])
        self.assertLessEqual(plan[1].size_sectors, self.partitions[1]["size"])
        self.assertEqual(plan[0].size_sectors, 2_000_000)
        self.assertEqual(plan[1].size_sectors, 6_000_000)

    def test_preserves_unallocated_space_when_source_partitions_are_smaller(self):
        plan = plan_proportional_gpt_layout(
            self.partitions,
            source_size_bytes=8_500_000_000,
            target_size_bytes=7_000_000_000,
            sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 1024 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
        )
        self.assertLessEqual(plan[0].size_sectors, self.partitions[0]["size"])
        self.assertLessEqual(plan[1].size_sectors, self.partitions[1]["size"])

    def test_requires_a_strictly_smaller_destination(self):
        with self.assertRaisesRegex(PartitionLayoutError, "smaller target"):
            plan_proportional_gpt_layout(
                self.partitions, source_size_bytes=8_500_000_000,
                target_size_bytes=8_500_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512, "/dev/source2": 1},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )


if __name__ == "__main__":
    unittest.main()
