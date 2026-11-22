from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "build" / "verify-iso-boot-visuals.sh"


class IsoBootVisualsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tools = self.root / "bin"
        self.tools.mkdir()
        self.iso = self.root / "test.iso"
        self.iso.write_bytes(b"test ISO")
        self.report = self.root / "report.txt"

        self._write_tool(
            "xorriso",
            """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

args = sys.argv[1:]
source = args[args.index("-extract") + 1]
destination = Path(args[args.index("-extract") + 2])
if source == "/images/pxeboot/initrd.img":
    destination.write_bytes(b"initrd")
elif source in ("/boot/grub2/grub.cfg", "/EFI/BOOT/grub.cfg"):
    kernel_args = "quiet" if os.environ.get("FAKE_NO_RHGB") else "rhgb quiet"
    if os.environ.get("FAKE_SELINUX_PERMISSIVE"):
        kernel_args += " enforcing=0"
    destination.write_text(f"menuentry test {{\\n linux /vmlinuz {kernel_args}\\n}}\\n")
else:
    raise SystemExit(1)
""",
        )
        self._write_tool(
            "lsinitrd",
            """#!/usr/bin/env python3
import os
import sys

if "-m" in sys.argv:
    print("base\\nplymouth")
elif "-f" in sys.argv:
    print("Theme=feclora")
else:
    assets = [
        "usr/share/plymouth/themes/feclora/feclora.plymouth",
        "usr/share/plymouth/themes/feclora/feclora.script",
        "usr/share/plymouth/themes/feclora/feclora-logo.png",
        "usr/lib64/plymouth/script.so",
    ]
    if os.environ.get("FAKE_MISSING_ASSET"):
        assets.remove(os.environ["FAKE_MISSING_ASSET"])
    print("\\n".join(assets))
""",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write_tool(self, name: str, source: str) -> None:
        path = self.tools / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    def _run_verifier(self, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.tools}{os.pathsep}{env['PATH']}"
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(VERIFIER), str(self.iso), str(self.report)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_accepts_iso_with_bios_uefi_and_feclora_plymouth_assets(self):
        result = self._run_verifier()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("BIOS kernel command lines", report)
        self.assertIn("UEFI kernel command lines", report)
        self.assertIn("ISO boot visual artifacts verified.", report)

    def test_rejects_bios_entry_without_plymouth_boot_argument(self):
        result = self._run_verifier(FAKE_NO_RHGB="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not enable the graphical Plymouth splash", result.stderr)

    def test_rejects_initramfs_missing_feclora_logo(self):
        result = self._run_verifier(
            FAKE_MISSING_ASSET="usr/share/plymouth/themes/feclora/feclora-logo.png"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing Plymouth asset", result.stderr)

    def test_accepts_permissive_mode_only_when_requested(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.tools}{os.pathsep}{env['PATH']}"
        env["FAKE_SELINUX_PERMISSIVE"] = "1"
        result = subprocess.run(
            ["bash", str(VERIFIER), str(self.iso), str(self.report), "permissive"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Expected SELinux mode: permissive", self.report.read_text(encoding="utf-8"))

    def test_rejects_missing_permissive_boot_argument(self):
        result = subprocess.run(
            ["bash", str(VERIFIER), str(self.iso), str(self.report), "permissive"],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{self.tools}{os.pathsep}{os.environ['PATH']}"},
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not enable diagnostic SELinux permissive mode", result.stderr)

    def test_rejects_permissive_argument_in_enforcing_build(self):
        env = os.environ.copy()
        env["PATH"] = f"{self.tools}{os.pathsep}{env['PATH']}"
        env["FAKE_SELINUX_PERMISSIVE"] = "1"
        result = subprocess.run(
            ["bash", str(VERIFIER), str(self.iso), str(self.report), "enforcing"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("enables diagnostic SELinux permissive mode in an enforcing build", result.stderr)


if __name__ == "__main__":
    unittest.main()
