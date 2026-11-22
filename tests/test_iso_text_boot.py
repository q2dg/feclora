from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "build" / "verify-iso-text-boot.sh"


class IsoTextBootTests(unittest.TestCase):
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
    kernel_args = "console=tty0 rd.systemd.show_status=1 systemd.show_status=1"
    if os.environ.get("FAKE_RHGB"):
        kernel_args += " rhgb quiet"
    if os.environ.get("FAKE_SELINUX_DISABLED"):
        kernel_args += " selinux=0"
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
    print("base")
else:
    print("usr/lib/dracut/hooks/cmdline/30-parse-root.sh")
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

    def test_accepts_text_mode_iso_without_plymouth_resources(self):
        result = self._run_verifier()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("BIOS kernel command lines", report)
        self.assertIn("UEFI kernel command lines", report)
        self.assertIn("ISO text-mode boot artifacts verified.", report)

    def test_rejects_splash_or_quiet_kernel_arguments(self):
        result = self._run_verifier(FAKE_RHGB="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still enables or references a boot splash or quiet boot", result.stderr)

    def test_rejects_disabling_selinux_in_the_generated_iso(self):
        result = self._run_verifier(FAKE_SELINUX_DISABLED="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disables SELinux completely", result.stderr)

    def test_rejects_plymouth_module_in_initramfs(self):
        self._write_tool(
            "lsinitrd",
            """#!/usr/bin/env python3
import sys
print("base\\nplymouth" if "-m" in sys.argv else "usr/share/plymouth/themes/default.plymouth")
""",
        )
        result = self._run_verifier()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("includes the Plymouth dracut module", result.stderr)

    def test_rejects_plymouth_files_without_the_module(self):
        self._write_tool(
            "lsinitrd",
            """#!/usr/bin/env python3
import sys
print("base" if "-m" in sys.argv else "usr/share/plymouth/themes/default.plymouth")
""",
        )
        result = self._run_verifier()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still contains boot-splash resources", result.stderr)

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
