import unittest

from feclora.storage.partition_layout import (
    PartitionLayoutError,
    plan_proportional_gpt_layout,
)


class ProportionalGPTLayoutTests(unittest.TestCase):
    def setUp(self):
        self.partitions = [
            {"node": "/dev/source1", "start": 2048, "size": 2_000_000,
             "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "uuid": "AAAA", "name": "EFI",
             "attrs": "RequiredPartition,NoBlockIOProtocol"},
            {"node": "/dev/source2", "start": 2_100_000, "size": 6_000_000,
             "type": "0fc63daf-8483-4772-8e79-3d69d8477de4", "uuid": "BBBB", "name": "root"},
        ]

    def test_plans_aligned_layout_that_fits_and_preserves_identity(self):
        plan = plan_proportional_gpt_layout(
            self.partitions,
            source_size_bytes=8_499_999_744,
            target_size_bytes=5_000_000_000,
            sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 1024 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
        )
        self.assertEqual([item.partuuid for item in plan], ["AAAA", "BBBB"])
        self.assertEqual([item.name for item in plan], ["EFI", "root"])
        self.assertEqual(plan[0].attributes, "RequiredPartition,NoBlockIOProtocol")
        self.assertEqual([item.start_sector for item in plan], [2048, 2_100_000])
        self.assertLessEqual(plan[-1].end_sector, 5_000_000_000 // 512 - 34)
        self.assertTrue(all(left.end_sector < right.start_sector for left, right in zip(plan, plan[1:])))
        self.assertEqual(plan[0].minimum_size_bytes, 2_000_000 * 512)

    def test_uses_inspected_nonstandard_gpt_usable_lba_geometry(self):
        source_sectors = 8_499_998_720 // 4096
        target_sectors = 4_999_999_488 // 4096
        source_last = source_sectors - 1 - 5
        partitions = [
            {"node": "/dev/source1", "start": 2048, "size": 250_000,
             "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
            {"node": "/dev/source2", "start": 260_000, "size": 1_000_000,
             "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"},
        ]
        plan = plan_proportional_gpt_layout(
            partitions,
            source_size_bytes=8_499_998_720,
            target_size_bytes=4_999_999_488,
            sector_size=4096,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 250_000 * 4096,
                                 "/dev/source2": 512 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            source_first_usable_lba=6,
            source_last_usable_lba=source_last,
        )
        self.assertEqual(plan[0].start_sector, 2048)
        self.assertLessEqual(plan[-1].end_sector, target_sectors - 1 - 5)

    def test_rejects_source_gpt_bounds_outside_source_capacity(self):
        with self.assertRaisesRegex(PartitionLayoutError, "source GPT usable-LBA bounds"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000,
                sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                     "/dev/source2": 1024 * 1024 * 1024},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
                source_first_usable_lba=34,
                source_last_usable_lba=8_500_000_000 // 512,
            )

    def test_rejects_invalid_gpt_partition_attributes(self):
        invalid = [dict(item) for item in self.partitions]
        invalid[0]["attrs"] = ["not", "a", "string"]
        with self.assertRaisesRegex(PartitionLayoutError, "invalid GPT attributes"):
            plan_proportional_gpt_layout(
                invalid, source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                     "/dev/source2": 1024 * 1024 * 1024},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )

    def test_rejects_minimum_sizes_that_do_not_fit(self):
        with self.assertRaisesRegex(PartitionLayoutError, "only the final source partition"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_499_999_744,
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
                source_size_bytes=8_499_999_744,
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
                overlapping, source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512, "/dev/source2": 1},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )
        unknown = [dict(item) for item in self.partitions]
        unknown[0].pop("type")
        with self.assertRaisesRegex(PartitionLayoutError, "valid GPT type GUID"):
            plan_proportional_gpt_layout(
                unknown, source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512, "/dev/source2": 1},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )


    def test_rejects_shrinking_non_ext_filesystem(self):
        with self.assertRaisesRegex(PartitionLayoutError, "only permits shrinking ext2/3/4 and NTFS"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_499_999_744,
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
            source_size_bytes=8_499_999_744,
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
            source_size_bytes=8_499_999_744,
            target_size_bytes=7_000_000_000,
            sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 1024 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
        )
        self.assertLessEqual(plan[0].size_sectors, self.partitions[0]["size"])
        self.assertLessEqual(plan[1].size_sectors, self.partitions[1]["size"])

    def test_keeps_known_non_ext_filesystems_fixed_size(self):
        plan = plan_proportional_gpt_layout(
            self.partitions, source_size_bytes=8_499_999_744,
            target_size_bytes=5_000_000_000, sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 6_000_000 * 512},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "xfs"},
        )
        self.assertEqual(plan[0].size_sectors, 2_000_000)
        self.assertEqual(plan[1].size_sectors, 6_000_000)

    def test_rejects_unknown_filesystem_or_storage_layer(self):
        with self.assertRaisesRegex(PartitionLayoutError, "unsupported filesystem or storage layer"):
            plan_proportional_gpt_layout(
                self.partitions, source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                     "/dev/source2": 6_000_000 * 512},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "LVM2_member"},
            )

    def test_shortens_only_the_final_ext_partition_and_preserves_starts(self):
        plan = plan_proportional_gpt_layout(
            self.partitions, source_size_bytes=8_499_999_744,
            target_size_bytes=4_000_000_000, sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 1024 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
        )
        self.assertEqual([item.start_sector for item in plan], [2048, 2_100_000])
        self.assertEqual(plan[0].size_sectors, 2_000_000)
        self.assertLess(plan[1].size_sectors, self.partitions[1]["size"])
        self.assertGreaterEqual(plan[1].size_sectors * 512, 1024 * 1024 * 1024)
        self.assertLessEqual(plan[-1].end_sector, 4_000_000_000 // 512 - 34)

    def test_shortens_final_ntfs_partition_when_native_minimum_fits(self):
        plan = plan_proportional_gpt_layout(
            self.partitions, source_size_bytes=8_499_999_744,
            target_size_bytes=4_000_000_000, sector_size=512,
            partition_table_type="gpt",
            minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                 "/dev/source2": 1024 * 1024 * 1024},
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ntfs"},
        )
        self.assertEqual(plan[-1].start_sector, self.partitions[-1]["start"])
        self.assertLess(plan[-1].size_sectors, self.partitions[-1]["size"])
        self.assertGreaterEqual(plan[-1].size_sectors * 512, 1024 * 1024 * 1024)
        self.assertLessEqual(plan[-1].end_sector, 4_000_000_000 // 512 - 34)

    def test_rejects_trimming_final_filesystems_without_a_verified_adapter(self):
        for filesystem in ("xfs", "f2fs", "exfat"):
            with self.subTest(filesystem=filesystem):
                with self.assertRaisesRegex(
                    PartitionLayoutError, "only ext2/3/4 and NTFS can be shortened"
                ):
                    plan_proportional_gpt_layout(
                        self.partitions, source_size_bytes=8_499_999_744,
                        target_size_bytes=4_000_000_000, sector_size=512,
                        partition_table_type="gpt",
                        minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                             "/dev/source2": 6_000_000 * 512},
                        filesystem_types={"/dev/source1": "vfat",
                                          "/dev/source2": filesystem},
                    )

    def test_rejects_layout_that_requires_relocating_later_partitions(self):
        with self.assertRaisesRegex(PartitionLayoutError, "only the final source partition"):
            plan_proportional_gpt_layout(
                self.partitions, source_size_bytes=8_499_999_744,
                target_size_bytes=1_000_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512,
                                     "/dev/source2": 1024 * 1024 * 1024},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )

    def test_requires_a_strictly_smaller_destination(self):
        with self.assertRaisesRegex(PartitionLayoutError, "smaller target"):
            plan_proportional_gpt_layout(
                self.partitions, source_size_bytes=8_499_999_744,
                target_size_bytes=8_500_000_000, sector_size=512,
                partition_table_type="gpt",
                minimum_sizes_bytes={"/dev/source1": 2_000_000 * 512, "/dev/source2": 1},
                filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            )


if __name__ == "__main__":
    unittest.main()
