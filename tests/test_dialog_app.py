import unittest

from feclora.ui.dialog_app import device_details


class DeviceDetailsTests(unittest.TestCase):
    def test_formats_device_and_nested_partition(self):
        details = device_details({
            "path": "/dev/sda",
            "type": "disk",
            "size_bytes": 1000,
            "read_only": False,
            "model": "Example",
            "children": [{
                "path": "/dev/sda1",
                "size_bytes": 900,
                "filesystem": "ext4",
                "children": [],
            }],
        })
        self.assertIn("Device: /dev/sda", details)
        self.assertIn("Model: Example", details)
        self.assertIn("/dev/sda1 | 900 bytes | ext4", details)

    def test_missing_fields_are_rendered_safely(self):
        details = device_details({"children": []})
        self.assertIn("Device: unknown", details)
        self.assertIn("Filesystem: none detected", details)


if __name__ == "__main__":
    unittest.main()
