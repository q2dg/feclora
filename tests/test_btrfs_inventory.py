import subprocess
import unittest

from feclora.storage.btrfs_inventory import (
    BtrfsInventoryError,
    collect_btrfs_topology,
    parse_filesystem_show,
)


SAMPLE = """Label: archive uuid: 01234567-89ab-cdef-0123-456789abcdef
        Total devices 2 FS bytes used 123456
        devid    1 size 1000000 path /dev/sda1
        devid    2 size 2000000 path /dev/sdb1
Label: none uuid: fedcba98-7654-3210-fedc-ba9876543210
        Total devices 1 FS bytes used 4096
        devid    1 size 500000 path /dev/nvme0n1p2
"""


class BtrfsInventoryTests(unittest.TestCase):
    def test_parses_multi_device_filesystems(self):
        result = parse_filesystem_show(SAMPLE)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["label"], "archive")
        self.assertEqual([d["path"] for d in result[0]["devices"]], ["/dev/sda1", "/dev/sdb1"])
        self.assertIsNone(result[1]["label"])

    def test_rejects_filesystem_without_devices(self):
        with self.assertRaises(BtrfsInventoryError):
            parse_filesystem_show("Label: none uuid: 01234567-89ab-cdef-0123-456789abcdef\n")

    def test_rejects_incomplete_multi_device_listing(self):
        payload = """Label: array uuid: 01234567-89ab-cdef-0123-456789abcdef
        Total devices 2 FS bytes used 123456
        devid    1 size 1000000 path /dev/sda1
"""
        with self.assertRaises(BtrfsInventoryError):
            parse_filesystem_show(payload)

    def test_collection_invokes_read_only_show(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, SAMPLE, "")
        result = collect_btrfs_topology(which=lambda name: "/usr/bin/btrfs", runner=runner)
        self.assertEqual(len(result["filesystems"]), 2)
        self.assertEqual(calls[0][1:], ["filesystem", "show", "--raw", "--all-devices"])


if __name__ == "__main__":
    unittest.main()
