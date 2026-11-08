import os
import tempfile
import unittest
from pathlib import Path

from feclora.storage.stratis_inventory import collect_stratis_topology


class StratisInventoryTests(unittest.TestCase):
    def test_discovers_pool_filesystems_and_recursive_backing_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dev" / "stratis"
            sysfs = Path(tmp) / "sys" / "class" / "block"
            (root / "poolA").mkdir(parents=True)
            (sysfs / "dm-3" / "slaves").mkdir(parents=True)
            (sysfs / "dm-3" / "slaves" / "dm-2").symlink_to(sysfs / "dm-2")
            (sysfs / "dm-2" / "slaves").mkdir(parents=True)
            (sysfs / "dm-2" / "slaves" / "sda1").symlink_to(sysfs / "sda1")
            (sysfs / "sda1").mkdir()
            os.symlink("/dev/dm-3", root / "poolA" / "fs1")
            result = collect_stratis_topology(str(root), str(sysfs))
            self.assertEqual(result["pools"][0]["name"], "poolA")
            fs = result["pools"][0]["filesystems"][0]
            self.assertEqual(fs["name"], "fs1")
            self.assertEqual(fs["backing_block_devices"], ["sda1"])

    def test_missing_stratis_device_root_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = collect_stratis_topology(str(Path(tmp) / "missing"), tmp)
            self.assertEqual(result, {"status": "unavailable", "pools": []})


if __name__ == "__main__":
    unittest.main()
