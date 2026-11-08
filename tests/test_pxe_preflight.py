import subprocess
import tempfile
import unittest
from pathlib import Path

from feclora.network.interface_discovery import InterfaceAddress
from feclora.network.pxe_config import PXENetworkConfig
from feclora.network.pxe_preflight import PXEPreflightError, validate_pxe_configuration


class PxePreflightTests(unittest.TestCase):
    def config(self):
        return PXENetworkConfig(
            interface="enp1s0", address="192.0.2.10", prefix_length=24,
            mode="proxy", tftp_root="/srv/feclora/tftp",
            bios_boot_file="undionly.kpxe", uefi_boot_file="snponly.efi",
            http_root="/srv/feclora/http",
        )

    def test_validates_interface_and_both_daemons_without_starting_them(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[0] == "/usr/sbin/dnsmasq":
                conf = Path(argv[2].split("=", 1)[1])
                self.assertTrue(conf.is_file())
                self.assertIn("dhcp-range=192.0.2.0,proxy", conf.read_text())
            return subprocess.CompletedProcess(argv, 0, "valid", "")
        def discover(interface, executable=None):
            return [InterfaceAddress(interface, "192.0.2.10", 24, "global", ("UP",))]
        with tempfile.TemporaryDirectory() as parent:
            validate_pxe_configuration(
                self.config(), dnsmasq="/usr/sbin/dnsmasq", caddy="/usr/bin/caddy",
                runner=runner, temp_parent=parent, address_discovery=discover,
            )
            self.assertEqual(list(Path(parent).iterdir()), [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], "--test")
        self.assertEqual(calls[1][1], "validate")

    def test_rejects_address_not_assigned_to_interface(self):
        def discover(interface, executable=None):
            return [InterfaceAddress(interface, "192.0.2.11", 24, "global", ("UP",))]
        with self.assertRaises(PXEPreflightError):
            validate_pxe_configuration(
                self.config(), dnsmasq="/usr/sbin/dnsmasq", caddy="/usr/bin/caddy",
                address_discovery=discover,
            )

    def test_reports_daemon_configuration_error(self):
        def runner(argv, **kwargs):
            raise subprocess.CalledProcessError(1, argv, stderr="invalid option")
        def discover(interface, executable=None):
            return [InterfaceAddress(interface, "192.0.2.10", 24, "global", ("UP",))]
        with self.assertRaisesRegex(PXEPreflightError, "invalid option"):
            validate_pxe_configuration(
                self.config(), dnsmasq="/usr/sbin/dnsmasq", caddy="/usr/bin/caddy",
                runner=runner, address_discovery=discover,
            )


if __name__ == "__main__":
    unittest.main()
