import unittest

from feclora.storage.capabilities import discover_capabilities


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_discovers_filesystem_specific_partclone_programs(self):
        paths = {
            "lsblk": "/usr/bin/lsblk",
            "partclone.ext4": "/usr/sbin/partclone.ext4",
            "partclone.ext2": "/usr/sbin/partclone.ext2",
            "partclone.ext3": "/usr/sbin/partclone.ext3",
            "fsck.exfat": "/usr/sbin/fsck.exfat",
            "fsck.f2fs": "/usr/sbin/fsck.f2fs",
            "partclone.ntfs": "/usr/sbin/partclone.ntfs",
            "sfdisk": "/usr/sbin/sfdisk",
            "dd": "/usr/bin/dd",
            "lvm": "/usr/sbin/lvm",
            "dmsetup": "/usr/sbin/dmsetup",
            "stratis": "/usr/bin/stratis",
        }
        calls = []

        def which(name):
            calls.append(name)
            return paths.get(name)

        result = discover_capabilities(which)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(
            result["groups"]["partclone"]["partclone.ext4"],
            "/usr/sbin/partclone.ext4",
        )
        self.assertEqual(
            result["groups"]["partition_tables"]["sfdisk"],
            "/usr/sbin/sfdisk",
        )
        self.assertIn("partclone.btrfs", result["missing"])
        self.assertEqual(result["groups"]["filesystem_checkers"]["fsck.exfat"], "/usr/sbin/fsck.exfat")
        self.assertEqual(result["groups"]["filesystem_checkers"]["fsck.f2fs"], "/usr/sbin/fsck.f2fs")
        self.assertIn("dd", result["available"])
        self.assertEqual(result["groups"]["volume_management"]["lvm"], "/usr/sbin/lvm")
        self.assertEqual(result["groups"]["volume_management"]["stratis"], "/usr/bin/stratis")
        self.assertEqual(result["status"], "executable_presence_only")
        self.assertEqual(len(calls), len(set(calls)))

    def test_missing_tools_are_reported_not_treated_as_fatal(self):
        result = discover_capabilities(lambda _name: None)
        self.assertEqual(result["available"], [])
        self.assertGreater(len(result["missing"]), 0)


if __name__ == "__main__":
    unittest.main()
