import json
import subprocess
import unittest

from feclora.network.interface_discovery import (
    InterfaceDiscoveryError,
    discover_interface_addresses,
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
