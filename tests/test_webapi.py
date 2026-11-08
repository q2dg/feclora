import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.webapi import WebAPIError, dispatch, _device


class WebAPITests(unittest.TestCase):
    def test_rejects_unknown_or_extra_request_fields(self):
        with self.assertRaisesRegex(WebAPIError, "action and optional params"):
            dispatch({"action": "status", "command": "id"})
        with self.assertRaisesRegex(WebAPIError, "unsupported"):
            dispatch({"action": "shell"})

    def test_rejects_parameters_for_read_only_actions(self):
        with self.assertRaisesRegex(WebAPIError, "does not accept parameters"):
            dispatch({"action": "status", "params": {"command": "id"}})

    def test_inventory_action_returns_only_inventory(self):
        with patch("feclora.webapi.collect_inventory", return_value={"devices": []}) as inventory:
            self.assertEqual(dispatch({"action": "inventory"}), {"devices": []})
        inventory.assert_called_once_with()

    def test_images_action_uses_manifest_inventory(self):
        with patch("feclora.webapi._images", return_value=[{"image_id": "base"}]):
            self.assertEqual(dispatch({"action": "images"}), {"images": [{"image_id": "base"}]})

    def test_operations_action_returns_durable_local_history(self):
        expected = [{"operation": "capture_disk", "status": "completed"}]
        with patch("feclora.webapi._operations", return_value=expected):
            self.assertEqual(dispatch({"action": "operations"}), {"operations": expected})

    def test_network_interfaces_action_returns_discovered_bindings(self):
        expected = [{"interface": "enp1s0", "address": "192.0.2.10", "prefix_length": 24,
                     "dhcp_server": None, "binding": "enp1s0|192.0.2.10|24"}]
        with patch("feclora.webapi._network_interfaces", return_value=expected):
            self.assertEqual(dispatch({"action": "network_interfaces"}), {"interfaces": expected})

    def test_bootstrap_server_requires_exact_parameters(self):
        with self.assertRaisesRegex(WebAPIError, "requires interface"):
            dispatch({"action": "bootstrap_server", "params": {"address": "192.0.2.10"}})

    def test_bootstrap_server_initializes_only_an_assigned_address(self):
        config = SimpleNamespace(
            bind_address="192.0.2.10", port=9443, local_identity="URI:feclora-server",
            client_identity_to_mac={}
        )
        with patch("feclora.network.interface_discovery.discover_interface_addresses", return_value=["address"]) as discover, \
             patch("feclora.network.interface_discovery.validate_selected_address") as validate, \
             patch("feclora.deployment.bootstrap.ensure_server_deployment_config", return_value=True) as bootstrap, \
             patch("feclora.deployment.runtime_config.load_server_runtime_config", return_value=config):
            result = dispatch({"action": "bootstrap_server", "params": {
                "interface": "enp1s0", "address": "192.0.2.10", "prefix_length": 24
            }})
        discover.assert_called_once_with("enp1s0")
        validate.assert_called_once_with("enp1s0", "192.0.2.10", 24, ["address"])
        bootstrap.assert_called_once_with("192.0.2.10")
        self.assertTrue(result["created"])
        self.assertEqual(result["bind_address"], "192.0.2.10")
        self.assertEqual(result["enrolled_clients"], 0)

    def test_bootstrap_server_validates_address_and_prefix_before_bootstrap(self):
        with self.assertRaisesRegex(WebAPIError, "prefix_length"):
            dispatch({"action": "bootstrap_server", "params": {
                "interface": "enp1s0", "address": "192.0.2.10", "prefix_length": True
            }})
        with self.assertRaisesRegex(WebAPIError, "IPv4"):
            dispatch({"action": "bootstrap_server", "params": {
                "interface": "enp1s0", "address": "2001:db8::1", "prefix_length": 64
            }})

    def test_device_paths_are_restricted_to_dev_nodes(self):
        self.assertEqual(_device("/dev/nvme0n1p2", "target"), "/dev/nvme0n1p2")
        for invalid in ("/etc/passwd", "/dev/../etc/shadow", "sda", "/dev/sda;id"):
            with self.subTest(invalid=invalid), self.assertRaises(WebAPIError):
                _device(invalid, "target")

    def test_destructive_action_requires_exact_parameter_set(self):
        with self.assertRaisesRegex(WebAPIError, "parameters do not match"):
            dispatch({"action": "clone_disk", "params": {"source": "/dev/sda", "target": "/dev/sdb"}})


if __name__ == "__main__":
    unittest.main()
