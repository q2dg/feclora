"""Safe, allowlisted Live keyboard-layout management."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any


# IDs are stable UI values; values are kbd(1) keymap names shipped by Fedora.
KEYMAPS = {
    "us": "us",
    "us-intl": "us-acentos",
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
KEYBOARD_CONFIG = Path("/etc/feclora/keyboard-layout.conf")


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
    try:
        info = os.lstat(KEYBOARD_CONFIG)
        if (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == 0 and info.st_size <= 4096):
            content = KEYBOARD_CONFIG.read_text(encoding="ascii")
            for line in content.splitlines():
                match = re.fullmatch(r"FECLORA_KEYBOARD_LAYOUT=([a-z-]{2,8})", line)
                if match and match.group(1) in KEYMAPS:
                    selected = match.group(1)
                    break
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError) as exc:
        raise KeyboardLayoutError(f"cannot read keyboard preference: {exc}") from exc
    return {"layout": selected or keymap, "keymap": keymap, "supported": sorted(KEYMAPS)}


def _write_keyboard_config(path: Path, layout_id: str) -> None:
    parent = path.parent
    parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    parent_info = os.lstat(parent)
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise KeyboardLayoutError("keyboard configuration directory is not a real directory")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    if info is not None and (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                             or info.st_size > 4096):
        raise KeyboardLayoutError("keyboard configuration is not a safe regular file")
    content = f"FECLORA_KEYBOARD_LAYOUT={layout_id}\n"
    fd, temporary = tempfile.mkstemp(prefix=".keyboard-layout-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def set_keyboard_layout(params: dict[str, Any], *, runner=None, config_path: Path = KEYBOARD_CONFIG) -> dict[str, Any]:
    if set(params) != {"layout"}:
        raise KeyboardLayoutError("set_keyboard_layout requires exactly layout")
    layout = params["layout"]
    if not isinstance(layout, str) or layout not in KEYMAPS:
        raise KeyboardLayoutError("keyboard layout is not in the supported allowlist")
    keymap = KEYMAPS[layout]
    run = runner or subprocess.run
    commands = (
        ["/usr/bin/localectl", "set-keymap", keymap],
        ["/usr/bin/loadkeys", keymap],
    )
    for command in commands:
        try:
            result = run(
                command, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, check=False, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise KeyboardLayoutError(f"could not apply keyboard layout {layout}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()[:256]
            raise KeyboardLayoutError(f"could not apply keyboard layout {layout}: {detail}")
    try:
        _write_keyboard_config(config_path, layout)
    except (OSError, subprocess.SubprocessError, KeyboardLayoutError) as exc:
        raise KeyboardLayoutError(f"could not save keyboard preference: {exc}") from exc
    return {"layout": layout, "keymap": keymap, "applied": True,
            "scope": "Linux virtual console"}
