import json
import subprocess
import unittest

from feclora.network.interface_discovery import (
    InterfaceDiscoveryError,
    discover_interface_addresses,
    detect_existing_dhcp_server,
    parse_interface_addresses,
    validate_selected_address,
)


PAYLOAD = json.dumps([{
    "ifname": "enp1s0",
    "flags": ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"],
    "addr_info": [
        {"family": "inet", "local": "192.0.2.10", "prefixlen": 24, "scope": "global"},
        {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"},
    ],
}])


class InterfaceDiscoveryTests(unittest.TestCase):
    def test_parses_only_usable_up_interface_addresses(self):
        values = parse_interface_addresses(PAYLOAD, "enp1s0")
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].network.with_prefixlen, "192.0.2.0/24")

    def test_rejects_interface_address_mismatch(self):
        values = parse_interface_addresses(PAYLOAD, "enp1s0")
        with self.assertRaises(InterfaceDiscoveryError):
            validate_selected_address("enp1s0", "192.0.2.11", 24, values)

    def test_ignores_down_interface(self):
        payload = json.dumps([{"ifname":"enp1s0","flags":["BROADCAST"],"addr_info":[
            {"family":"inet","local":"192.0.2.10","prefixlen":24}
        ]}])
        self.assertEqual(parse_interface_addresses(payload, "enp1s0"), [])

    def test_detects_dhcp_server_from_existing_nm_lease(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0, "dhcp_lease_time = 3600\ndhcp_server_identifier = 192.0.2.254\n", ""
            )
        self.assertEqual(
            detect_existing_dhcp_server("enp1s0", nmcli="/usr/bin/nmcli", runner=runner),
            "192.0.2.254",
        )

    def test_absence_of_nmcli_or_lease_is_not_reported_as_a_server(self):
        self.assertIsNone(detect_existing_dhcp_server("enp1s0", nmcli="/missing"))

    def test_discovery_uses_read_only_ip_json_command(self):
        seen = []
        def runner(argv, **kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, PAYLOAD, "")
        result = discover_interface_addresses("enp1s0", executable="/usr/sbin/ip", runner=runner)
        self.assertEqual(result[0].address, "192.0.2.10")
        self.assertEqual(seen[0][1:], ["-j", "-4", "address", "show", "dev", "enp1s0"])


if __name__ == "__main__":
    unittest.main()


class NetworkConnectionProfileTests(unittest.TestCase):
    def test_parses_safe_connection_profile_inventory(self):
        from feclora.network.connection_profiles import parse_connection_profiles
        payload = json.dumps([{
            "NAME": "Management LAN", "UUID": "12345678-1234-1234-1234-123456789abc",
            "TYPE": "ethernet", "DEVICE": "enp1s0", "ACTIVE": True,
            "connection.autoconnect": "yes", "IP4.METHOD": "manual",
            "IP4.ADDRESS": ["192.0.2.10/24"], "IP4.GATEWAY": "192.0.2.1",
            "IP4.DNS": ["192.0.2.53"], "802-1x.password": "must-not-leak",
        }])
        result = parse_connection_profiles(payload)
        self.assertEqual(result[0]["ipv4_method"], "manual")
        self.assertEqual(result[0]["ipv4_addresses"], ["192.0.2.10/24"])
        self.assertNotIn("password", json.dumps(result))

    def test_ignores_unsupported_and_malformed_profiles(self):
        from feclora.network.connection_profiles import parse_connection_profiles
        payload = json.dumps([
            {"NAME": "VPN", "UUID": "12345678-1234-1234-1234-123456789abc", "TYPE": "vpn"},
            {"NAME": "Broken", "UUID": "not-a-uuid", "TYPE": "ethernet"},
        ])
        self.assertEqual(parse_connection_profiles(payload), [])

    def test_rejects_invalid_nmcli_json(self):
        from feclora.network.connection_profiles import NetworkProfileError, parse_connection_profiles
        with self.assertRaises(NetworkProfileError):
            parse_connection_profiles("{")
