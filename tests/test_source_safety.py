import json
import subprocess
import unittest

from feclora.storage.source_safety import SourceSafetyError, check_capture_source_safe


class SourceSafetyTests(unittest.TestCase):
    def test_rejects_mounted_partition(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "blockdevices": [{"path": "/dev/sda1", "type": "part", "mountpoints": ["/data"]}]
            }), "")
        with self.assertRaisesRegex(SourceSafetyError, "mounted"):
            check_capture_source_safe(
                "/dev/sda1", runner=runner, which=lambda name: name,
                root_disk_resolver=lambda **kwargs: {"/dev/nvme0n1"},
            )

    def test_rejects_live_root_backing_disk(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "blockdevices": [{"path": "/dev/sda", "type": "disk", "mountpoints": [],
                                  "children": [{"path": "/dev/sda1", "type": "part", "mountpoints": []}]}]
            }), "")
        with self.assertRaisesRegex(SourceSafetyError, "live system root"):
            check_capture_source_safe(
                "/dev/sda1", runner=runner, which=lambda name: name,
                root_disk_resolver=lambda **kwargs: {"/dev/sda"},
            )

    def test_rejects_unverifiable_root_protection(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "blockdevices": [{"path": "/dev/sdb1", "type": "part", "mountpoints": []}]
            }), "")
        def fail(**kwargs):
            raise RuntimeError("findmnt failed")
        with self.assertRaises(SourceSafetyError):
            check_capture_source_safe(
                "/dev/sdb1", runner=runner, which=lambda name: name,
                root_disk_resolver=fail,
            )

    def test_requires_lsblk(self):
        with self.assertRaisesRegex(SourceSafetyError, "lsblk"):
            check_capture_source_safe("/dev/sda1", which=lambda _name: None)


if __name__ == "__main__":
    unittest.main()
