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
KIOSK_KEYBOARD_CONFIG = Path("/etc/feclora/kiosk-keyboard.conf")
XKB_LAYOUTS = {
    "us": ("us", ""), "us-intl": ("us", "intl"),
    "es": ("es", ""), "ca": ("es", "cat"), "gl": ("es", ""), "eu": ("es", ""), "fr": ("fr", ""), "de": ("de", ""),
    "it": ("it", ""), "pt": ("pt", ""), "br": ("br", ""),
    "ru": ("ru", ""), "tr": ("tr", ""), "ar": ("ara", ""),
    "ja": ("jp", ""), "zh": ("cn", ""),
}


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
        info = os.lstat(KIOSK_KEYBOARD_CONFIG)
        if (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == 0 and info.st_size <= 4096):
            content = KIOSK_KEYBOARD_CONFIG.read_text(encoding="ascii")
            for line in content.splitlines():
                match = re.fullmatch(r"FECLORA_KEYBOARD_LAYOUT=([a-z-]{2,8})", line)
                if match and match.group(1) in KEYMAPS:
                    selected = match.group(1)
                    break
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError) as exc:
        raise KeyboardLayoutError(f"cannot read kiosk keyboard preference: {exc}") from exc
    return {"layout": selected or keymap, "keymap": keymap, "supported": sorted(KEYMAPS)}


def _write_kiosk_keyboard_config(path: Path, layout_id: str, layout: str, variant: str) -> None:
    parent = path.parent
    parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    parent_info = os.lstat(parent)
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise KeyboardLayoutError("kiosk keyboard configuration directory is not a real directory")
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    if info is not None and (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                             or info.st_size > 4096):
        raise KeyboardLayoutError("kiosk keyboard configuration is not a safe regular file")
    content = f"FECLORA_KEYBOARD_LAYOUT={layout_id}\nXKB_DEFAULT_LAYOUT={layout}\nXKB_DEFAULT_VARIANT={variant}\nXKB_DEFAULT_OPTIONS=\n"
    fd, temporary = tempfile.mkstemp(prefix=".kiosk-keyboard-", dir=parent)
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


def set_keyboard_layout(params: dict[str, Any], *, runner=None, config_path: Path = KIOSK_KEYBOARD_CONFIG) -> dict[str, Any]:
    if set(params) != {"layout"}:
        raise KeyboardLayoutError("set_keyboard_layout requires exactly layout")
    layout = params["layout"]
    if not isinstance(layout, str) or layout not in KEYMAPS:
        raise KeyboardLayoutError("keyboard layout is not in the supported allowlist")
    keymap = KEYMAPS[layout]
    xkb_layout, xkb_variant = XKB_LAYOUTS[layout]
    run = runner or subprocess.run

    def available_values(command: list[str], label: str) -> set[str]:
        try:
            result = run(
                command, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, check=False, timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise KeyboardLayoutError(f"could not validate XKB {label}: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()[:256]
            raise KeyboardLayoutError(f"could not validate XKB {label}: {detail}")
        return {
            match.group(1)
            for line in (result.stdout or "").splitlines()
            if (match := re.match(r"^\s*([A-Za-z0-9_-]+)(?:\s|$)", line))
        }

    layouts = available_values(
        ["/usr/bin/localectl", "list-x11-keymap-layouts"], "layout availability",
    )
    if xkb_layout not in layouts:
        raise KeyboardLayoutError(f"XKB layout {xkb_layout} is not installed on this Live image")
    if xkb_variant:
        variants = available_values(
            ["/usr/bin/localectl", "list-x11-keymap-variants", xkb_layout],
            f"variant availability for {xkb_layout}",
        )
        if xkb_variant not in variants:
            raise KeyboardLayoutError(
                f"XKB variant {xkb_layout}({xkb_variant}) is not installed on this Live image"
            )
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
        _write_kiosk_keyboard_config(config_path, layout, xkb_layout, xkb_variant)
        restart = run(
            ["/usr/bin/systemd-run", "--unit=feclora-keyboard-restart",
             "--on-active=2s", "--collect", "/usr/bin/systemctl", "restart",
             "feclora-kiosk.service"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError, KeyboardLayoutError) as exc:
        raise KeyboardLayoutError(f"could not configure graphical keyboard layout: {exc}") from exc
    if restart.returncode != 0:
        detail = (restart.stderr or restart.stdout or "systemd could not schedule the kiosk restart").strip()[:256]
        raise KeyboardLayoutError(f"keyboard saved but graphical kiosk restart was not scheduled: {detail}")
    return {"layout": layout, "keymap": keymap, "xkb_layout": xkb_layout,
            "xkb_variant": xkb_variant, "applied": True,
            "scope": "persistent Linux console and Cage/Wayland XKB; kiosk session restarts shortly"}
