import unittest

from feclora.deployment.server_ui import _flatten_devices


class ServerUIDeviceSelectionTests(unittest.TestCase):
    def test_flatten_devices_includes_nested_partitions(self):
        inventory = [{
            "path": "/dev/nvme0n1", "type": "disk", "children": [
                {"path": "/dev/nvme0n1p1", "type": "part", "read_only": True, "children": [
                    {"path": "/dev/mapper/data", "type": "crypt", "children": []},
                ]},
            ],
        }]
        flattened = _flatten_devices(inventory)
        self.assertEqual(
            [item["path"] for item in flattened],
            ["/dev/nvme0n1", "/dev/nvme0n1p1", "/dev/mapper/data"],
        )
        self.assertTrue(flattened[1]["read_only"])


if __name__ == "__main__":
    unittest.main()
