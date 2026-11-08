import unittest
from types import SimpleNamespace

from feclora.network.multicast_preflight import (
    MulticastPreflightError, inspect_multicast_interface,
)


class MulticastPreflightTests(unittest.TestCase):
    def test_sender_preflight_checks_up_multicast_interface_address_route_and_tool(self):
        outputs = iter([
            "2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500",
            "2: enp1s0 inet 192.0.2.10/24 scope global enp1s0",
            "multicast 239.10.10.1 dev enp1s0 src 192.0.2.10",
        ])
        calls = []
        def runner(argv, **_kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")
        result = inspect_multicast_interface(
            "enp1s0", "239.10.10.1", role="sender",
            runner=runner, which=lambda name: "/usr/bin/" + name,
        )
        self.assertEqual(result.ipv4_address, "192.0.2.10")
        self.assertEqual(result.route_interface, "enp1s0")
        self.assertEqual(len(calls), 3)
        self.assertTrue(any("IGMP" in item for item in result.warnings))

    def test_rejects_interface_without_multicast_flag(self):
        outputs = iter(["2: enp1s0: <BROADCAST,UP,LOWER_UP> mtu 1500"])
        with self.assertRaisesRegex(MulticastPreflightError, "support multicast"):
            inspect_multicast_interface(
                "enp1s0", "239.10.10.1", role="receiver",
                runner=lambda *_args, **_kwargs: SimpleNamespace(
                    returncode=0, stdout=next(outputs), stderr="",
                ),
            )

    def test_rejects_kernel_route_through_another_interface(self):
        outputs = iter([
            "2: enp1s0: <BROADCAST,MULTICAST,UP> mtu 1500",
            "2: enp1s0 inet 192.0.2.10/24 scope global enp1s0",
            "multicast 239.10.10.1 dev enp2s0 src 192.0.2.20",
        ])
        with self.assertRaisesRegex(MulticastPreflightError, "uses enp2s0"):
            inspect_multicast_interface(
                "enp1s0", "239.10.10.1", role="receiver",
                runner=lambda *_args, **_kwargs: SimpleNamespace(
                    returncode=0, stdout=next(outputs), stderr="",
                ),
            )


if __name__ == "__main__":
    unittest.main()
