"""Startup mode selector for the single feclora Live ISO.

Only the local inventory mode is currently implemented. Server and client
choices are deliberately visible but fail closed until their services and
deployment runtime are implemented.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from feclora.ui.dialog_app import main as run_live


def _dialog(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dialog", "--stdout", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    if shutil.which("dialog") is None:
        print("feclora: install the 'dialog' package to use this interface", file=sys.stderr)
        return 1

    while True:
        result = _dialog([
            "--clear",
            "--title", "feclora - Select operating mode",
            "--menu",
            "One ISO, multiple operating modes. Network services start only when selected.",
            "18", "84", "6",
            "live", "Local rescue: inspect and manage this machine",
            "server", "Server: coordinate network imaging deployments",
            "client", "Client: join a network imaging deployment",
            "reboot", "Reboot",
            "poweroff", "Power off",
        ])

        if result.returncode != 0:
            return 0

        choice = result.stdout.strip()
        if choice == "live":
            return run_live()
        if choice == "server":
            _dialog([
                "--title", "Server mode not yet implemented",
                "--msgbox",
                "Server mode is part of this single ISO target, but its control plane, PXE services and deployment transport are not implemented yet. No network service has been started.",
                "10", "76",
            ])
        elif choice == "client":
            _dialog([
                "--title", "Client mode not yet implemented",
                "--msgbox",
                "Client mode is part of this single ISO target, but the PXE client runtime and authenticated job protocol are not implemented yet.",
                "10", "76",
            ])
        elif choice == "reboot":
            subprocess.run(["systemctl", "reboot"], check=False)
            return 0
        elif choice == "poweroff":
            subprocess.run(["systemctl", "poweroff"], check=False)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
