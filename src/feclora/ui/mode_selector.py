"""Startup mode selector and live-console keyboard configuration."""
from __future__ import annotations

import shutil
import subprocess
import sys

from feclora.ui.dialog_app import main as run_live
from feclora.network.server_mode import run_server_ui

KEYBOARD_LAYOUTS = {
    "es": "Spanish (Spain)",
    "us": "English (US)",
    "gb": "English (UK)",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "latam": "Spanish (Latin America)",
}


def _dialog(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dialog", "--stdout", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _select_keyboard() -> None:
    choices = [(layout, label) for layout, label in KEYBOARD_LAYOUTS.items()]
    args = [
        "--title", "Keyboard layout",
        "--menu",
        "Select the physical keyboard layout for this live session. This does not change the image language.",
        "18", "78", "8",
    ]
    for value, label in choices:
        args.extend([value, label])
    result = _dialog(args)
    if result.returncode != 0:
        return
    layout = result.stdout.strip()
    if layout not in KEYBOARD_LAYOUTS:
        return
    loadkeys = shutil.which("loadkeys")
    if not loadkeys:
        _dialog(["--title", "Keyboard layout", "--msgbox",
                 "The kbd/loadkeys utility is unavailable in this image.", "8", "70"])
        return
    try:
        applied = subprocess.run(
            [loadkeys, layout], check=False, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = str(exc)
        applied = None
    else:
        detail = (applied.stderr or applied.stdout or "").strip()
    if applied is None or applied.returncode != 0:
        _dialog(["--title", "Keyboard layout error", "--msgbox",
                 f"Could not apply keyboard layout {layout}: {detail}", "10", "76"])
    else:
        _dialog(["--title", "Keyboard layout", "--msgbox",
                 f"Keyboard layout set to {KEYBOARD_LAYOUTS[layout]} for this live session.", "8", "70"])


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
            "20", "84", "7",
            "live", "Local rescue: inspect and manage this machine",
            "server", "Server: coordinate network imaging deployments",
            "client", "Client: join a network imaging deployment",
            "keyboard", "Configure keyboard layout",
            "reboot", "Reboot",
            "poweroff", "Power off",
        ])

        if result.returncode != 0:
            return 0

        choice = result.stdout.strip()
        if choice == "live":
            return run_live()
        if choice == "server":
            run_server_ui()
        elif choice == "client":
            from feclora.deployment.client_ui import run_client_ui
            run_client_ui()
        elif choice == "keyboard":
            _select_keyboard()
        elif choice == "reboot":
            subprocess.run(["systemctl", "reboot"], check=False)
            return 0
        elif choice == "poweroff":
            subprocess.run(["systemctl", "poweroff"], check=False)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
