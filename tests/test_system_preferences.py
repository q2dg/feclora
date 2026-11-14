import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from feclora.system_preferences import (
    KEYMAPS, KeyboardLayoutError, get_keyboard_layout, set_keyboard_layout,
)


class KeyboardLayoutTests(unittest.TestCase):
    def test_layout_aliases_are_allowlisted_and_resolve_to_kernel_keymaps(self):
        self.assertEqual(KEYMAPS["ca"], "es")
        self.assertEqual(KEYMAPS["eu"], "es")
        self.assertEqual(KEYMAPS["ja"], "jp106")

    def test_rejects_unknown_layout_before_running_commands(self):
        with patch("feclora.system_preferences.subprocess.run") as run:
            with self.assertRaises(KeyboardLayoutError):
                set_keyboard_layout({"layout": "../../etc/passwd"})
        run.assert_not_called()

    def test_requires_exact_parameter_shape(self):
        with patch("feclora.system_preferences.subprocess.run") as run:
            with self.assertRaises(KeyboardLayoutError):
                set_keyboard_layout({"layout": "us", "command": "arbitrary"})
        run.assert_not_called()

    def test_applies_persistent_and_active_console_keymap_without_shell(self):
        result = Mock(returncode=0, stdout="", stderr="")
        with patch("feclora.system_preferences.subprocess.run", return_value=result) as run:
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "kiosk-keyboard.conf"
                applied = set_keyboard_layout({"layout": "ca"}, config_path=config)
                self.assertIn("FECLORA_KEYBOARD_LAYOUT=ca", config.read_text())
                self.assertIn("XKB_DEFAULT_LAYOUT=es", config.read_text())
                self.assertIn("XKB_DEFAULT_VARIANT=cat", config.read_text())
                self.assertTrue(config.read_text().endswith("XKB_DEFAULT_OPTIONS=\n"))
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["keymap"], "es")
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/localectl", "set-keymap", "es"])
        self.assertEqual(run.call_args_list[1].args[0], ["/usr/bin/loadkeys", "es"])
        self.assertEqual(run.call_args_list[2].args[0], ["/usr/bin/systemd-run", "--unit=feclora-keyboard-restart", "--on-active=2s", "--collect", "/usr/bin/systemctl", "restart", "feclora-kiosk.service"])
        self.assertIs(run.call_args_list[0].kwargs["check"], False)

    def test_reads_the_exact_saved_layout_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "kiosk-keyboard.conf"
            config.write_text("FECLORA_KEYBOARD_LAYOUT=ca\nXKB_DEFAULT_LAYOUT=es\n")
            original_lstat = os.lstat
            def trusted_lstat(path):
                info = original_lstat(path)
                if Path(path) == config:
                    return type("TrustedStat", (), {
                        "st_mode": stat.S_IFREG | 0o644,
                        "st_uid": 0,
                        "st_size": info.st_size,
                    })()
                return info
            with patch("feclora.system_preferences.KIOSK_KEYBOARD_CONFIG", config), \\
                 patch("feclora.system_preferences.os.lstat", side_effect=trusted_lstat):
                self.assertEqual(get_keyboard_layout()["layout"], "ca")

    def test_reports_command_failure(self):
        result = Mock(returncode=1, stdout="", stderr="missing keymap")
        with patch("feclora.system_preferences.subprocess.run", return_value=result):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(KeyboardLayoutError, "missing keymap"):
                    set_keyboard_layout({"layout": "us"}, config_path=Path(directory) / "kiosk-keyboard.conf")


if __name__ == "__main__":
    unittest.main()
