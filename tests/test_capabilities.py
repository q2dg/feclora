import unittest

from feclora.storage.capabilities import discover_capabilities


class CapabilityDiscoveryTests(unittest.TestCase):
    def test_groups_available_and_missing_tools_without_running_them(self):
        paths = {"lsblk": "/usr/bin/lsblk", "partclone": "/usr/sbin/partclone"}
        calls = []

        def which(name):
            calls.append(name)
            return paths.get(name)

        result = discover_capabilities(which)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["groups"]["inventory"]["lsblk"], "/usr/bin/lsblk")
        self.assertEqual(result["groups"]["imaging"]["partclone"], "/usr/sbin/partclone")
        self.assertIn("dd", result["missing"])
        self.assertEqual(result["status"], "executable_presence_only")
        self.assertEqual(set(calls), set(result["available"]) | set(result["missing"]))

    def test_missing_tools_are_reported_not_treated_as_fatal(self):
        result = discover_capabilities(lambda _name: None)
        self.assertEqual(result["available"], [])
        self.assertGreater(len(result["missing"]), 0)


if __name__ == "__main__":
    unittest.main()
