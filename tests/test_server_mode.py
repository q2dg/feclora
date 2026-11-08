import unittest

from feclora.network.interface_discovery import InterfaceAddress
from feclora.network.server_mode import build_server_config


class ServerModeConfigTests(unittest.TestCase):
    def setUp(self):
        self.interface = InterfaceAddress("enp1s0", "192.0.2.10", 24, "global", ("UP",))

    def test_proxy_profile_is_the_safe_default(self):
        config = build_server_config(self.interface, "proxy")
        self.assertEqual(config.mode, "proxy")
        self.assertIsNone(config.pool_start)
        self.assertEqual(config.uefi_boot_file, "ipxe-snponly-x86_64.efi")

    def test_isolated_profile_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            build_server_config(
                self.interface, "isolated",
                pool_start="192.0.2.20", pool_end="192.0.2.80",
            )

    def test_isolated_profile_accepts_explicit_pool_and_confirmation(self):
        config = build_server_config(
            self.interface, "isolated",
            pool_start="192.0.2.20", pool_end="192.0.2.80",
            authoritative_confirmed=True,
        )
        self.assertEqual(config.pool_start, "192.0.2.20")
        self.assertTrue(config.authoritative_confirmed)


if __name__ == "__main__":
    unittest.main()
