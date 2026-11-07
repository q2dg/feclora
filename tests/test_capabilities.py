import unittest

from feclora.storage.capabilities import discover_capabilities


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_discovers_filesystem_specific_partclone_programs(self):
        paths = {
            "lsblk": "/usr/bin/lsblk",
            "partclone.ext4": "/usr/sbin/partclone.ext4",
            "partclone.ntfs": "/usr/sbin/partclone.ntfs",
            "sfdisk": "/usr/sbin/sfdisk",
            "dd": "/usr/bin/dd",
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
        self.assertIn("dd", result["available"])
        self.assertEqual(result["status"], "executable_presence_only")
        self.assertEqual(len(calls), len(set(calls)))

    def test_missing_tools_are_reported_not_treated_as_fatal(self):
        result = discover_capabilities(lambda _name: None)
        self.assertEqual(result["available"], [])
        self.assertGreater(len(result["missing"]), 0)


if __name__ == "__main__":
    unittest.main()
