import unittest

from feclora.storage.partition_layout import (
    PartitionLayoutError,
    plan_proportional_gpt_layout,
)


class ProportionalGPTLayoutTests(unittest.TestCase):
    def setUp(self):
        self.partitions = [
            {"node": "/dev/source1", "start": 2048, "size": 2_000_000,
             "type": "EF00", "uuid": "AAAA", "name": "EFI"},
            {"node": "/dev/source2", "start": 2_100_000, "size": 6_000_000,
             "type": "8300", "uuid": "BBBB", "name": "root"},
        ]

    def test_plans_aligned_layout_that_fits_and_preserves_identity(self):
        plan = plan_proportional_gpt_layout(
            self.partitions,
            source_size_bytes=8_500_000_000,
            target_size_bytes=5_000_000_000,
            sector_size=512,
            minimum_sizes_bytes={"/dev/source1": 256 * 1024 * 1024,
                                 "/dev/source2": 1024 * 1024 * 1024},
        )
        self.assertEqual([item.partuuid for item in plan], ["AAAA", "BBBB"])
        self.assertEqual([item.name for item in plan], ["EFI", "root"])
        self.assertTrue(all(item.start_sector * 512 % (1024 * 1024) == 0 for item in plan))
        self.assertLessEqual(plan[-1].end_sector, 5_000_000_000 // 512 - 34)

    def test_rejects_minimum_sizes_that_do_not_fit(self):
        with self.assertRaisesRegex(PartitionLayoutError, "do not fit"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_500_000_000,
                target_size_bytes=1_000_000_000,
                sector_size=512,
                minimum_sizes_bytes={"/dev/source1": 600_000_000,
                                     "/dev/source2": 600_000_000},
            )

    def test_requires_minimum_for_every_partition(self):
        with self.assertRaisesRegex(PartitionLayoutError, "filesystem minimum"):
            plan_proportional_gpt_layout(
                self.partitions,
                source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000,
                sector_size=512,
                minimum_sizes_bytes={"/dev/source1": 256 * 1024 * 1024},
            )

    def test_rejects_overlap_and_unknown_partition_type(self):
        overlapping = [dict(item) for item in self.partitions]
        overlapping[1]["start"] = 1_500_000
        with self.assertRaisesRegex(PartitionLayoutError, "overlap"):
            plan_proportional_gpt_layout(
                overlapping, source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000, sector_size=512,
                minimum_sizes_bytes={"/dev/source1": 1, "/dev/source2": 1},
            )
        unknown = [dict(item) for item in self.partitions]
        unknown[0].pop("type")
        with self.assertRaisesRegex(PartitionLayoutError, "type GUID"):
            plan_proportional_gpt_layout(
                unknown, source_size_bytes=8_500_000_000,
                target_size_bytes=5_000_000_000, sector_size=512,
                minimum_sizes_bytes={"/dev/source1": 1, "/dev/source2": 1},
            )

    def test_requires_a_strictly_smaller_destination(self):
        with self.assertRaisesRegex(PartitionLayoutError, "smaller target"):
            plan_proportional_gpt_layout(
                self.partitions, source_size_bytes=8_500_000_000,
                target_size_bytes=8_500_000_000, sector_size=512,
                minimum_sizes_bytes={"/dev/source1": 1, "/dev/source2": 1},
            )


if __name__ == "__main__":
    unittest.main()
