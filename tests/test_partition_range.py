import hashlib
import tempfile
import unittest

from feclora.storage.partition_range import (
    PartitionRangeError,
    copy_fd_range,
    load_sfdisk_json,
    partition_ranges,
    parse_sfdisk_dump,
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
            self.assertEqual(result.sha256, hashlib.sha256(b"456789ab").hexdigest())

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

    def test_rejects_overlapping_partition_ranges(self):
        table = {"partitiontable": {"partitions": [
            {"node": "/dev/loop0p1", "start": 10, "size": 20},
            {"node": "/dev/loop0p2", "start": 25, "size": 20},
        ]}}
        with self.assertRaises(PartitionRangeError):
            partition_ranges(table, image_size_bytes=64 * 512)

    def test_copy_rejects_source_range_past_end(self):
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as target:
            source.write(b"small")
            source.flush()
            target.truncate(16)
            with self.assertRaises(PartitionRangeError):
                copy_fd_range(source.fileno(), target.fileno(), source_offset=2, length=8)

    def test_parses_sfdisk_dump_from_whole_disk_capture(self):
        dump = ('label: gpt\nsector-size: 512\n'
                '/dev/sda1 : start=2048, size=4096, type=EF00, uuid=1111-AAAA, name="EFI System"\n'
                '/dev/sda2 : start=6144, size=8192, type=8300, uuid=2222-BBBB, name="root"\n')
        table = parse_sfdisk_dump(dump, image_size_bytes=16 * 1024 * 1024)
        selected = select_partition_range(
            table, "EFI System", image_size_bytes=16 * 1024 * 1024
        )
        self.assertEqual(selected.node, "/dev/sda1")


if __name__ == "__main__":
    unittest.main()
