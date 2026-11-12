import subprocess
import unittest

from feclora.storage.btrfs_inventory import (
    BtrfsInventoryError,
    collect_btrfs_topology,
    collect_btrfs_subvolumes,
    parse_filesystem_show,
    parse_filesystem_profiles,
    parse_subvolume_list,
    parse_root_tree_subvolumes,
    parse_chunk_tree,
)


SAMPLE = """Label: archive uuid: 01234567-89ab-cdef-0123-456789abcdef
        Total devices 2 FS bytes used 123456
        devid    1 size 1000000 path /dev/sda1
        devid    2 size 2000000 path /dev/sdb1
Label: none uuid: fedcba98-7654-3210-fedc-ba9876543210
        Total devices 1 FS bytes used 4096
        devid    1 size 500000 path /dev/nvme0n1p2
"""


PROFILE_SAMPLE = """Data, single: total=1150000000 used=1130000000
Metadata, DUP: total=12000000000 used=6450000000
System, DUP: total=32000000 used=144000
GlobalReserve, single: total=512000000 used=0
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

    def test_parses_data_metadata_and_system_profiles_without_losing_redundancy(self):
        profiles = parse_filesystem_profiles(PROFILE_SAMPLE)
        by_type = {item["type"]: item for item in profiles if item["type"] != "globalreserve"}
        self.assertEqual(by_type["data"]["profile"], "single")
        self.assertEqual(by_type["metadata"]["profile"], "dup")
        self.assertEqual(by_type["metadata"]["total_bytes"], 12000000000)
        self.assertTrue(by_type["metadata"]["known_profile"])

    def test_preserves_unknown_profile_but_marks_it_unsupported(self):
        profiles = parse_filesystem_profiles(
            "Data, future-raid: total=100 used=50\nMetadata, single: total=100 used=50\n"
        )
        self.assertFalse(profiles[0]["known_profile"])
        self.assertEqual(profiles[0]["profile"], "future-raid")

    def test_rejects_malformed_or_incomplete_profile_report(self):
        with self.assertRaises(BtrfsInventoryError):
            parse_filesystem_profiles(
                "Data, single: total=100 used=101\nMetadata, single: total=100 used=50\n"
            )
        with self.assertRaises(BtrfsInventoryError):
            parse_filesystem_profiles("Data, single: total=100 used=50\n")

    def test_collection_invokes_read_only_show(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if "dump-tree" not in argv:
                output = SAMPLE
            elif "root" in argv:
                output = ROOT_TREE
            else:
                output = CHUNK_TREE
            return subprocess.CompletedProcess(argv, 0, output, "")
        result = collect_btrfs_topology(which=lambda name: "/usr/bin/btrfs", runner=runner, effective_uid=lambda: 0)
        self.assertEqual(len(result["filesystems"]), 2)
        self.assertEqual(calls[0][1:], ["filesystem", "show", "--raw", "--all-devices"])
        self.assertIn("--noscan", calls[1])
        self.assertEqual(calls[1][-2:], ["/dev/sda1", "/dev/sdb1"])
        self.assertEqual(calls[2][-2:], ["/dev/sda1", "/dev/sdb1"])
        self.assertEqual(result["filesystems"][0]["subvolumes"][1]["path"], "@/pre-upgrade")
        self.assertEqual(result["filesystems"][0]["allocation_profiles"][0]["profile"], "raid1")


SUBVOLUMES = """ID 256 gen 100 parent 5 top level 5 parent_uuid - received_uuid - uuid 11111111-1111-1111-1111-111111111111 path @
ID 257 gen 120 parent 256 top level 5 parent_uuid 11111111-1111-1111-1111-111111111111 received_uuid - uuid 22222222-2222-2222-2222-222222222222 path @snapshots/pre-upgrade
"""


ROOT_TREE = """item 0 key (256 ROOT_ITEM 0) itemoff 100 itemsize 439
        generation 100 root_dirid 256 bytenr 100000 byte_limit 0 bytes_used 4096
        last_snapshot 0 flags 0x0(none) refs 1
        level 0 generation_v2 100
        uuid 11111111-1111-1111-1111-111111111111
        parent_uuid 00000000-0000-0000-0000-000000000000
        received_uuid 00000000-0000-0000-0000-000000000000
item 1 key (257 ROOT_ITEM 120) itemoff 200 itemsize 439
        generation 120 root_dirid 256 bytenr 200000 byte_limit 0 bytes_used 8192
        last_snapshot 120 flags 0x1(RDONLY) refs 1
        level 0 generation_v2 120
        uuid 22222222-2222-2222-2222-222222222222
        parent_uuid 11111111-1111-1111-1111-111111111111
        received_uuid 00000000-0000-0000-0000-000000000000
item 2 key (258 ROOT_ITEM 0) itemoff 300 itemsize 439
        generation 130 root_dirid 256 bytenr 300000 byte_limit 0 bytes_used 2048
        last_snapshot 0 flags 0x0(none) refs 1
        level 0 generation_v2 130
        uuid 33333333-3333-3333-3333-333333333333
        parent_uuid 00000000-0000-0000-0000-000000000000
        received_uuid 44444444-4444-4444-4444-444444444444
item 3 key (256 ROOT_BACKREF 5) itemoff 400 itemsize 20
        root backref key dirid 256 sequence 0 name @
item 4 key (257 ROOT_BACKREF 256) itemoff 420 itemsize 20
        root backref key dirid 256 sequence 1 name pre-upgrade
item 5 key (258 ROOT_BACKREF 5) itemoff 440 itemsize 20
        root backref key dirid 256 sequence 0 name received
"""


CHUNK_TREE = """item 0 key (FIRST_CHUNK_TREE CHUNK_ITEM 1048576) itemoff 100 itemsize 80
        length 1048576 owner 2 stripe_len 65536 type DATA|RAID1
        io_align 4096 io_width 4096 sector_size 4096
        num_stripes 2 sub_stripes 1
                stripe 0 devid 1 offset 0
                dev_uuid 11111111-1111-1111-1111-111111111111
                stripe 1 devid 2 offset 0
                dev_uuid 22222222-2222-2222-2222-222222222222
item 1 key (FIRST_CHUNK_TREE CHUNK_ITEM 2097152) itemoff 200 itemsize 80
        length 262144 owner 2 stripe_len 65536 type METADATA|DUP
        io_align 4096 io_width 4096 sector_size 4096
        num_stripes 2 sub_stripes 1
                stripe 0 devid 1 offset 1048576
                dev_uuid 11111111-1111-1111-1111-111111111111
                stripe 1 devid 1 offset 1310720
                dev_uuid 11111111-1111-1111-1111-111111111111
"""


class BtrfsSubvolumeTests(unittest.TestCase):


    def test_unmounted_chunk_tree_reports_profiles_and_stripe_devices(self):
        chunks, profiles = parse_chunk_tree(CHUNK_TREE, known_device_ids={1, 2})
        self.assertEqual(chunks[0]["profile"], "raid1")
        self.assertEqual(chunks[0]["device_ids"], [1, 2])
        self.assertTrue(chunks[0]["device_mapping_complete"])
        by_type = {item["type"]: item for item in profiles}
        self.assertEqual(by_type["data"]["total_bytes"], 1048576)
        self.assertEqual(by_type["data"]["device_ids"], [1, 2])
        self.assertEqual(by_type["metadata"]["profile"], "dup")
        self.assertEqual(by_type["metadata"]["device_ids"], [1])
        self.assertIsNone(by_type["metadata"]["used_bytes"])

    def test_chunk_tree_preserves_unknown_profiles_and_rejects_missing_stripes(self):
        unknown = CHUNK_TREE.replace("DATA|RAID1", "DATA|FUTURE_RAID")
        _chunks, profiles = parse_chunk_tree(unknown, known_device_ids={1, 2})
        self.assertFalse(next(item for item in profiles if item["type"] == "data")["known_profile"])
        incomplete = CHUNK_TREE.split("item 1", 1)[0].replace("stripe 1 devid 2 offset 0", "")
        with self.assertRaisesRegex(BtrfsInventoryError, "reports 2 stripes"):
            parse_chunk_tree(incomplete)

    def test_unmounted_root_tree_reports_snapshot_and_received_ancestry(self):
        result = parse_root_tree_subvolumes(ROOT_TREE)
        by_id = {item["id"]: item for item in result}
        self.assertEqual(by_id[256]["kind"], "subvolume")
        self.assertEqual(by_id[256]["path"], "@")
        self.assertEqual(by_id[257]["kind"], "snapshot")
        self.assertTrue(by_id[257]["readonly"])
        self.assertEqual(by_id[257]["parent_subvolume_id"], 256)
        self.assertEqual(by_id[257]["path"], "@/pre-upgrade")
        self.assertEqual(by_id[258]["kind"], "received_subvolume")
        self.assertEqual(by_id[258]["received_uuid"], "44444444-4444-4444-4444-444444444444")

    def test_root_tree_rejects_duplicate_roots_and_invalid_uuid(self):
        with self.assertRaisesRegex(BtrfsInventoryError, "duplicate current ROOT_ITEM"):
            parse_root_tree_subvolumes(ROOT_TREE + ROOT_TREE.split("item 1", 1)[1].join(["item 1", ""]))
        malformed = ROOT_TREE.replace(
            "uuid 11111111-1111-1111-1111-111111111111",
            "uuid not-a-uuid",
            1,
        )
        with self.assertRaisesRegex(BtrfsInventoryError, "invalid subvolume UUID"):
            parse_root_tree_subvolumes(malformed)

    def test_distinguishes_snapshot_from_regular_subvolume_by_parent_uuid(self):
        result = parse_subvolume_list(SUBVOLUMES)
        self.assertEqual([item["kind"] for item in result], ["subvolume", "snapshot"])
        self.assertFalse(result[0]["is_snapshot"])
        self.assertTrue(result[1]["is_snapshot"])
        self.assertEqual(result[1]["parent_uuid"], result[0]["uuid"])

    def test_records_received_subvolume_without_assuming_it_is_a_snapshot(self):
        row = "ID 258 gen 130 parent 5 top level 5 parent_uuid - received_uuid 33333333-3333-3333-3333-333333333333 uuid 44444444-4444-4444-4444-444444444444 path received-subvolume"
        result = parse_subvolume_list(row)
        self.assertEqual(result[0]["kind"], "received_subvolume")
        self.assertFalse(result[0]["is_snapshot"])
        self.assertEqual(result[0]["received_uuid"], "33333333-3333-3333-3333-333333333333")

    def test_rejects_unrecognized_rows_instead_of_guessing(self):
        with self.assertRaises(BtrfsInventoryError):
            parse_subvolume_list("ID 256 path @")

    def test_no_mounted_btrfs_filesystems_is_an_empty_inventory(self):
        def runner(argv, **kwargs):
            error = subprocess.CalledProcessError(1, argv, stderr="")
            raise error
        result = collect_btrfs_subvolumes(
            which=lambda name: "/usr/bin/" + name,
            runner=runner,
            effective_uid=lambda: 0,
        )
        self.assertEqual(result, {"status": "available", "mounts": []})

    def test_inspects_only_already_mounted_btrfs_filesystems(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if any("findmnt" in str(part) for part in argv):
                return subprocess.CompletedProcess(argv, 0, '{"filesystems":[{"target":"/mnt/data","source":"/dev/sda1","uuid":"01234567-89ab-cdef-0123-456789abcdef"}]}', "")
            if "filesystem" in argv and "df" in argv:
                return subprocess.CompletedProcess(argv, 0, PROFILE_SAMPLE, "")
            return subprocess.CompletedProcess(argv, 0, SUBVOLUMES, "")
        result = collect_btrfs_subvolumes(
            which=lambda name: "/usr/bin/" + name,
            runner=runner,
            effective_uid=lambda: 0,
        )
        self.assertEqual(result["mounts"][0]["mountpoint"], "/mnt/data")
        self.assertEqual(result["mounts"][0]["source"], "/dev/sda1")
        self.assertEqual(result["mounts"][0]["uuid"], "01234567-89ab-cdef-0123-456789abcdef")
        self.assertIn("SOURCE,UUID", calls[0][calls[0].index("--output") + 1])
        self.assertEqual(len(result["mounts"][0]["subvolumes"]), 2)
        self.assertEqual(result["mounts"][0]["allocation_profiles"][1]["profile"], "dup")
        self.assertTrue(any("findmnt" in str(part) for part in calls[0]))
        self.assertEqual(calls[1][-6:], ["-a", "-p", "-u", "-q", "-R", "/mnt/data"])
        self.assertEqual(calls[2][-3:], ["df", "--raw", "/mnt/data"])


if __name__ == "__main__":
    unittest.main()
