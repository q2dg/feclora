import subprocess
import tempfile
import unittest
from pathlib import Path

from feclora.network.boot_assets import BootAssetError, stage_ipxe_assets


class BootAssetTests(unittest.TestCase):
    def test_stages_exact_rpm_owned_files_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "rpm-files"
            source.mkdir()
            (source / "undionly.kpxe").write_bytes(b"bios")
            (source / "ipxe-snponly-x86_64.efi").write_bytes(b"uefi")
            listing = "\n".join(str(p) for p in source.iterdir()) + "\n"
            def runner(argv, **kwargs):
                self.assertEqual(argv, ["/usr/bin/rpm", "-ql", "ipxe-bootimgs-x86"])
                return subprocess.CompletedProcess(argv, 0, listing, "")
            target = root / "tftp"
            result = stage_ipxe_assets(
                str(target), rpm="/usr/bin/rpm", runner=runner,
            )
            self.assertEqual(Path(result["undionly.kpxe"]).read_bytes(), b"bios")
            self.assertEqual(Path(result["ipxe-snponly-x86_64.efi"]).read_bytes(), b"uefi")
            self.assertEqual((target / "undionly.kpxe").stat().st_mode & 0o777, 0o444)
            # Re-staging the exact same RPM payload is safe and idempotent.
            again = stage_ipxe_assets(str(target), rpm="/usr/bin/rpm", runner=runner)
            self.assertEqual(again, result)

    def test_rejects_missing_or_ambiguous_firmware(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "/usr/share/ipxe/undionly.kpxe\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BootAssetError):
                stage_ipxe_assets(tmp, rpm="/usr/bin/rpm", runner=runner)

    def test_refuses_to_overwrite_existing_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            src.mkdir()
            (src / "undionly.kpxe").write_bytes(b"bios")
            (src / "ipxe-snponly-x86_64.efi").write_bytes(b"uefi")
            target = root / "target"
            target.mkdir()
            (target / "undionly.kpxe").write_bytes(b"old")
            listing = "\n".join(str(p) for p in src.iterdir())
            def runner(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, listing, "")
            with self.assertRaises(BootAssetError):
                stage_ipxe_assets(str(target), rpm="/usr/bin/rpm", runner=runner)


if __name__ == "__main__":
    unittest.main()
