import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.network.pxe_boot import PXEBootTreeError, stage_pxe_boot_tree
from feclora.network.pxe_config import PXENetworkConfig


def config(root):
    return PXENetworkConfig(
        interface="enp1s0", address="192.0.2.10", prefix_length=24,
        mode="proxy", tftp_root=str(Path(root) / "tftp"),
        bios_boot_file="undionly.kpxe", uefi_boot_file="ipxe-snponly-x86_64.efi",
        http_root=str(Path(root) / "http"),
    )


class PxeBootTreeTests(unittest.TestCase):
    def test_stages_both_firmware_and_live_http_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rpm_files = root / "rpm"
            rpm_files.mkdir()
            (rpm_files / "undionly.kpxe").write_bytes(b"bios")
            (rpm_files / "ipxe-snponly-x86_64.efi").write_bytes(b"uefi")
            live = root / "live"
            (live / "images" / "pxeboot").mkdir(parents=True)
            (live / "LiveOS").mkdir()
            (live / "images" / "pxeboot" / "vmlinuz").write_bytes(b"kernel")
            (live / "images" / "pxeboot" / "initrd.img").write_bytes(b"initrd")
            (live / "LiveOS" / "squashfs.img").write_bytes(b"squashfs")
            def runner(argv, **kwargs):
                return __import__("subprocess").CompletedProcess(
                    argv, 0, "\\n".join(str(p) for p in rpm_files.iterdir()), ""
                )
            with patch("feclora.network.pxe_boot.stage_ipxe_assets") as stage_tftp, patch(
                "feclora.network.pxe_boot.stage_live_boot_assets"
            ) as stage_http:
                stage_tftp.return_value = {"undionly.kpxe": "tftp/undionly.kpxe"}
                stage_http.return_value = {"boot.ipxe": "http/boot.ipxe"}
                result = stage_pxe_boot_tree(
                    config(root), live_root=str(live),
                    account_lookup=lambda _name: SimpleNamespace(pw_uid=100, pw_gid=100),
                )
            self.assertEqual(result["tftp"]["undionly.kpxe"], "tftp/undionly.kpxe")
            stage_tftp.assert_called_once()
            stage_http.assert_called_once()

    def test_requires_dnsmasq_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PXEBootTreeError):
                stage_pxe_boot_tree(config(tmp), account_lookup=lambda _name: (_ for _ in ()).throw(KeyError()))


if __name__ == "__main__":
    unittest.main()
