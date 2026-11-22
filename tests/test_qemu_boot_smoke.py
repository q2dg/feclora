from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST = ROOT / "tests" / "vm" / "run-boot-smoke.py"


class QemuBootSmokeTests(unittest.TestCase):
    def test_runs_bios_and_uefi_and_accepts_rendered_tui_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_qemu = root / "fake-qemu"
            fake_qemu.write_text(
                """#!/usr/bin/env python3
import socket
import sys
import time

channel = next(arg for arg in sys.argv if arg.startswith("socket,id=boot-smoke,"))
path = next(part[5:] for part in channel.split(",") if part.startswith("path="))
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path)
server.listen(1)
connection, _ = server.accept()
connection.sendall(b"FECLORA_BOOT_SMOKE rendered\\n")
time.sleep(30)
""",
                encoding="utf-8",
            )
            fake_qemu.chmod(0o755)
            iso = root / "feclora.iso"
            iso.write_bytes(b"test ISO")
            ovmf_code = root / "OVMF_CODE.fd"
            ovmf_vars = root / "OVMF_VARS.fd"
            ovmf_code.write_bytes(b"firmware")
            ovmf_vars.write_bytes(b"firmware-vars")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SMOKE_TEST),
                    "--iso",
                    str(iso),
                    "--qemu",
                    str(fake_qemu),
                    "--timeout",
                    "5",
                    "--ovmf-code",
                    str(ovmf_code),
                    "--ovmf-vars",
                    str(ovmf_vars),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BIOS:", result.stdout)
        self.assertIn("UEFI:", result.stdout)


if __name__ == "__main__":
    unittest.main()
