"""Safe, allowlisted Live keyboard-layout management."""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


# IDs are stable UI values; values are kbd(1) keymap names shipped by Fedora.
KEYMAPS = {
    "us": "us",
    "us-intl": "us",
    "es": "es",
    "ca": "es",
    "gl": "es",
    "eu": "es",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "pt": "pt-latin1",
    "br": "br-abnt2",
    "ru": "ru",
    "tr": "trq",
    "ar": "ara",
    "ja": "jp106",
    "zh": "us",
}
VCONSOLE_CONFIG = Path("/etc/vconsole.conf")


class KeyboardLayoutError(RuntimeError):
    """A keyboard layout could not be safely read or applied."""


def _read_keymap() -> str:
    try:
        info = os.lstat(VCONSOLE_CONFIG)
    except FileNotFoundError:
        return "us"
    except OSError as exc:
        raise KeyboardLayoutError(f"cannot inspect virtual-console configuration: {exc}") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0 or info.st_size > 4096):
        raise KeyboardLayoutError("virtual-console configuration is not a safe root-owned regular file")
    try:
        content = VCONSOLE_CONFIG.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise KeyboardLayoutError(f"cannot read virtual-console configuration: {exc}") from exc
    for line in content.splitlines():
        match = re.fullmatch(r'\s*KEYMAP\s*=\s*"?([A-Za-z0-9_-]{1,32})"?\s*', line)
        if match:
            return match.group(1)
    return "us"


def get_keyboard_layout() -> dict[str, Any]:
    keymap = _read_keymap()
    selected = next((name for name, value in KEYMAPS.items() if value == keymap), None)
    return {"layout": selected or keymap, "keymap": keymap, "supported": sorted(KEYMAPS)}


def set_keyboard_layout(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"layout"}:
        raise KeyboardLayoutError("set_keyboard_layout requires exactly layout")
    layout = params["layout"]
    if not isinstance(layout, str) or layout not in KEYMAPS:
        raise KeyboardLayoutError("keyboard layout is not in the supported allowlist")
    keymap = KEYMAPS[layout]
    commands = (
        ["/usr/bin/localectl", "set-keymap", keymap],
        ["/usr/bin/loadkeys", keymap],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, check=False, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise KeyboardLayoutError(f"could not apply keyboard layout {layout}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()[:256]
            raise KeyboardLayoutError(f"could not apply keyboard layout {layout}: {detail}")
    return {"layout": layout, "keymap": keymap, "applied": True,
            "scope": "persistent virtual-console keymap and active Linux console"}
