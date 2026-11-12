import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from feclora.deployment.server_ui import _flatten_devices, _run_unicast_job


class ServerUIDeviceSelectionTests(unittest.TestCase):
    def test_unicast_clone_dispatches_to_remote_clone_runtime(self):
        control = Mock()
        config = SimpleNamespace()
        job = SimpleNamespace(operation="clone")
        result = _run_unicast_job(control, config, job, "02:00:00:00:00:01", None)
        control.run_remote_clone_job.assert_called_once_with()
        control.run_one_client_job.assert_not_called()
        self.assertEqual(result, control.run_remote_clone_job.return_value)

    def test_unicast_restore_keeps_image_transfer_runtime(self):
        control = Mock()
        config = SimpleNamespace(
            repository="/srv/images",
        )
        job = SimpleNamespace(operation="restore")
        _run_unicast_job(control, config, job, "02:00:00:00:00:01", "/srv/images/os.manifest.json")
        control.run_one_client_job.assert_called_once_with(
            "/srv/images",
            manifest_path="/srv/images/os.manifest.json",
        )
        control.run_remote_clone_job.assert_not_called()

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
