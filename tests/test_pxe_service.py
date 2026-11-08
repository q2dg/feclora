import subprocess
import tempfile
import unittest
from pathlib import Path

from feclora.network.pxe_config import PXENetworkConfig
from feclora.network.pxe_service import PXEServiceError, PXEServiceManager


def config():
    return PXENetworkConfig(
        interface="enp1s0", address="192.0.2.10", prefix_length=24,
        mode="proxy", tftp_root="/srv/feclora/tftp",
        bios_boot_file="undionly.kpxe", uefi_boot_file="ipxe-snponly-x86_64.efi",
        http_root="/srv/feclora/http",
    )


class FakeFirewall:
    def __init__(self):
        self.opened = []
        self.closed = []
    def open(self, interface, ports):
        self.opened.append((interface, list(ports)))
    def close(self, interface):
        self.closed.append(interface)
    def export_state(self, interface):
        return {"zone": "feclora-pxe-a1b2c3d4", "restore_zone": "public", "ports": ["67/udp", "4011/udp", "8080/tcp"]}
    def adopt(self, interface, state):
        self.adopted = (interface, state)


class PxeServiceTests(unittest.TestCase):
    def test_starts_two_explicit_transient_units_and_writes_private_configs(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            firewall = FakeFirewall()
            manager = PXEServiceManager(tmp, runner=runner, preflight=lambda _config: None, firewall=firewall, boot_stager=lambda _config: None)
            manager.start(config())
            starts = [call for call in calls if call[0].endswith("systemd-run")]
            self.assertEqual(len(starts), 2)
            self.assertTrue(any(arg.startswith("--unit=feclora-dnsmasq-") for arg in starts[0]))
            self.assertTrue(any(arg.startswith("--unit=feclora-caddy-") for arg in starts[1]))
            self.assertEqual((Path(tmp) / "dnsmasq.conf").stat().st_mode & 0o777, 0o600)
            self.assertEqual((Path(tmp) / "Caddyfile").stat().st_mode & 0o777, 0o644)
            self.assertNotIn("enable", " ".join(calls[0]))
            self.assertEqual(firewall.opened[0][0], "enp1s0")
            manager.stop()
            self.assertEqual(firewall.closed, ["enp1s0"])

    def test_rolls_back_when_caddy_start_fails(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[0].endswith("systemd-run") and any(arg.startswith("--unit=feclora-caddy-") for arg in argv):
                raise subprocess.CalledProcessError(1, argv, stderr="Caddy failed")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            firewall = FakeFirewall()
            manager = PXEServiceManager(tmp, runner=runner, preflight=lambda _config: None, firewall=firewall, boot_stager=lambda _config: None)
            with self.assertRaises(PXEServiceError):
                manager.start(config())
        self.assertTrue(any(argv[:2] == ["/usr/bin/systemctl", "stop"] for argv in calls))
        self.assertEqual(firewall.closed, ["enp1s0"])


    def test_fresh_manager_can_stop_services_started_by_another_api_process(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            firewall1 = FakeFirewall()
            first = PXEServiceManager(tmp, runner=runner, preflight=lambda _config: None,
                                      firewall=firewall1, boot_stager=lambda _config: None)
            first.start(config())
            firewall2 = FakeFirewall()
            second = PXEServiceManager(tmp, runner=runner, preflight=lambda _config: None,
                                       firewall=firewall2, boot_stager=lambda _config: None)
            second.stop()
            self.assertEqual(firewall2.adopted[0], "enp1s0")
            self.assertEqual(firewall2.closed, ["enp1s0"])
            self.assertFalse((Path(tmp) / "active.json").exists())

    def test_rejects_symlink_runtime_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real)
            manager = PXEServiceManager(str(link), runner=lambda *a, **k: None, preflight=lambda _config: None, firewall=FakeFirewall(), boot_stager=lambda _config: None)
            with self.assertRaises(PXEServiceError):
                manager.start(config())


if __name__ == "__main__":
    unittest.main()
