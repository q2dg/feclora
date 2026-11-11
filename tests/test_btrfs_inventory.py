import subprocess
import unittest

from feclora.storage.btrfs_inventory import (
    BtrfsInventoryError,
    collect_btrfs_topology,
    collect_btrfs_subvolumes,
    parse_filesystem_show,
    parse_subvolume_list,
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
        result = collect_btrfs_topology(which=lambda name: "/usr/bin/btrfs", runner=runner, effective_uid=lambda: 0)
        self.assertEqual(len(result["filesystems"]), 2)
        self.assertEqual(calls[0][1:], ["filesystem", "show", "--raw", "--all-devices"])


SUBVOLUMES = """ID 256 gen 100 parent 5 top level 5 parent_uuid - received_uuid - uuid 11111111-1111-1111-1111-111111111111 path @
ID 257 gen 120 parent 256 top level 5 parent_uuid 11111111-1111-1111-1111-111111111111 received_uuid - uuid 22222222-2222-2222-2222-222222222222 path @snapshots/pre-upgrade
"""


class BtrfsSubvolumeTests(unittest.TestCase):
    def test_distinguishes_snapshot_from_regular_subvolume_by_parent_uuid(self):
        result = parse_subvolume_list(SUBVOLUMES)
        self.assertEqual([item["kind"] for item in result], ["subvolume", "snapshot"])
        self.assertFalse(result[0]["is_snapshot"])
        self.assertTrue(result[1]["is_snapshot"])
        self.assertEqual(result[1]["parent_uuid"], result[0]["uuid"])

    def test_rejects_unrecognized_rows_instead_of_guessing(self):
        with self.assertRaises(BtrfsInventoryError):
            parse_subvolume_list("ID 256 path @")

    def test_inspects_only_already_mounted_btrfs_filesystems(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if "findmnt" in argv:
                return subprocess.CompletedProcess(argv, 0, '{"filesystems":[{"target":"/mnt/data"}]}', "")
            return subprocess.CompletedProcess(argv, 0, SUBVOLUMES, "")
        result = collect_btrfs_subvolumes(
            which=lambda name: "/usr/bin/" + name,
            runner=runner,
            effective_uid=lambda: 0,
        )
        self.assertEqual(result["mounts"][0]["mountpoint"], "/mnt/data")
        self.assertEqual(len(result["mounts"][0]["subvolumes"]), 2)
        self.assertIn("findmnt", calls[0])
        self.assertEqual(calls[1][-5:], ["-a", "-p", "-u", "-q", "/mnt/data"])


if __name__ == "__main__":
    unittest.main()
