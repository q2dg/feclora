import json
import subprocess
import unittest
from unittest.mock import patch

from feclora.storage.inventory import (
    InventoryError,
    collect_inventory,
    parse_lsblk,
)


SAMPLE = {
    "blockdevices": [
        {
            "name": "/dev/sda",
            "path": "/dev/sda",
            "type": "disk",
            "size": 1000000,
            "ro": False,
            "tran": "sata",
            "model": "Example disk",
            "vendor": "Example",
            "serial": "SERIAL-1",
            "wwn": None,
            "children": [
                {
                    "name": "/dev/sda1",
                    "path": "/dev/sda1",
                    "type": "part",
                    "size": 900000,
                    "ro": False,
                    "fstype": "ext4",
                    "label": "root",
                    "uuid": "uuid-1",
                    "mountpoints": ["/"],
                }
            ],
        }
    ]
}


class ParseInventoryTests(unittest.TestCase):
    def test_normalizes_disk_and_partition(self):
        inventory = parse_lsblk(json.dumps(SAMPLE))
        disk = inventory["devices"][0]
        self.assertEqual(inventory["schema_version"], 1)
        self.assertEqual(disk["path"], "/dev/sda")
        self.assertEqual(disk["size_bytes"], 1000000)
        self.assertEqual(disk["children"][0]["filesystem"], "ext4")
        self.assertEqual(disk["children"][0]["mountpoints"], ["/"])

    def test_missing_optional_fields_are_safe(self):
        inventory = parse_lsblk('{"blockdevices":[{"name":"loop0","type":"loop"}]}')
        device = inventory["devices"][0]
        self.assertIsNone(device["serial"])
        self.assertEqual(device["mountpoints"], [])
        self.assertEqual(device["children"], [])

    def test_rejects_invalid_json(self):
        with self.assertRaises(InventoryError):
            parse_lsblk("{not-json}")

    def test_rejects_unexpected_document(self):
        with self.assertRaises(InventoryError):
            parse_lsblk('{"devices":[]}')

    @patch("feclora.storage.inventory.shutil.which", return_value="/usr/bin/lsblk")
    def test_collect_invokes_lsblk_in_query_only_mode(self, _which):
        completed = subprocess.CompletedProcess(
            args=["lsblk"], returncode=0, stdout=json.dumps(SAMPLE), stderr=""
        )
        with patch(
            "feclora.storage.inventory.subprocess.run", return_value=completed
        ) as runner:
            inventory = collect_inventory()
        command = runner.call_args.args[0]
        self.assertIn("--json", command)
        self.assertIn("--bytes", command)
        self.assertIn("--output", command)
        self.assertNotIn("wipefs", command)
        self.assertEqual(len(inventory["devices"]), 1)

    @patch("feclora.storage.inventory.shutil.which", return_value="/usr/bin/lsblk")
    def test_reports_lsblk_failure(self, _which):
        error = subprocess.CalledProcessError(1, ["lsblk"], stderr="permission error")
        with patch(
            "feclora.storage.inventory.subprocess.run", side_effect=error
        ):
            with self.assertRaisesRegex(InventoryError, "permission error"):
                collect_inventory()


if __name__ == "__main__":
    unittest.main()
