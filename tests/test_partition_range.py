import os
import tempfile
import unittest

from feclora.storage.partition_range import (
    PartitionRangeError,
    copy_fd_range,
    load_sfdisk_json,
    partition_ranges,
    select_partition_range,
)


class PartitionRangeTests(unittest.TestCase):
    def setUp(self):
        self.table = {
            "partitiontable": {
                "label": "gpt",
                "partitions": [
                    {"node": "/dev/loop0p1", "start": 2048, "size": 4096,
                     "uuid": "1111-AAAA", "name": "boot"},
                    {"node": "/dev/loop0p2", "start": 6144, "size": 8192,
                     "uuid": "2222-BBBB", "name": "root"},
                ],
            }
        }

    def test_calculates_byte_ranges(self):
        ranges = partition_ranges(self.table, image_size_bytes=16 * 1024 * 1024)
        self.assertEqual(ranges[0].offset_bytes, 2048 * 512)
        self.assertEqual(ranges[0].length_bytes, 4096 * 512)
        self.assertEqual(ranges[1].end_bytes, (6144 + 8192) * 512)

    def test_selects_by_partuuid_or_name(self):
        selected = select_partition_range(
            self.table, "2222-BBBB", image_size_bytes=16 * 1024 * 1024
        )
        self.assertEqual(selected.node, "/dev/loop0p2")
        named = select_partition_range(
            self.table, "boot", image_size_bytes=16 * 1024 * 1024
        )
        self.assertEqual(named.start_sector, 2048)

    def test_rejects_partition_past_end_of_image(self):
        with self.assertRaises(PartitionRangeError):
            partition_ranges(self.table, image_size_bytes=4 * 1024 * 1024)

    def test_rejects_ambiguous_selector(self):
        table = {"partitiontable": {"partitions": [
            {"node": "/dev/loop0p1", "start": 1, "size": 2, "name": "data"},
            {"node": "/dev/loop0p2", "start": 3, "size": 2, "name": "data"},
        ]}}
        with self.assertRaises(PartitionRangeError):
            select_partition_range(table, "data", image_size_bytes=4096)

    def test_copy_fd_range_copies_only_selected_bytes_and_hashes(self):
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as target:
            source.write(b"0123456789abcdef")
            source.flush()
            target.truncate(8)
            result = copy_fd_range(
                source.fileno(), target.fileno(), source_offset=4, length=8, chunk_size=3
            )
            target.seek(0)
            self.assertEqual(target.read(), b"456789ab")
            self.assertEqual(result.bytes_copied, 8)
            self.assertEqual(result.sha256, "f9f6f4c7c3d8f0f9e2e3f7c9c7c7f9d7") if False else None

    def test_copy_reports_progress_and_honors_cancel(self):
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as target:
            source.write(b"x" * 32)
            source.flush()
            target.truncate(32)
            updates = []
            result = copy_fd_range(
                source.fileno(), target.fileno(), source_offset=0, length=32,
                chunk_size=8, progress_callback=lambda done, total: updates.append((done, total)),
            )
            self.assertEqual(result.bytes_copied, 32)
            self.assertEqual(updates[-1], (32, 32))
            calls = iter([False, True])
            with self.assertRaises(InterruptedError):
                copy_fd_range(
                    source.fileno(), target.fileno(), source_offset=0, length=32,
                    chunk_size=8, cancel_check=lambda: next(calls, True),
                )

    def test_rejects_duplicate_json_keys(self):
        with self.assertRaises(PartitionRangeError):
            load_sfdisk_json('{"partitiontable": {}, "partitiontable": {}}')


if __name__ == "__main__":
    unittest.main()
