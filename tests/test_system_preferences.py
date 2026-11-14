import unittest
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
            applied = set_keyboard_layout({"layout": "ca"})
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["keymap"], "es")
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/localectl", "set-keymap", "es"])
        self.assertEqual(run.call_args_list[1].args[0], ["/usr/bin/loadkeys", "es"])
        self.assertIs(run.call_args_list[0].kwargs["check"], False)

    def test_reports_command_failure(self):
        result = Mock(returncode=1, stdout="", stderr="missing keymap")
        with patch("feclora.system_preferences.subprocess.run", return_value=result):
            with self.assertRaisesRegex(KeyboardLayoutError, "missing keymap"):
                set_keyboard_layout({"layout": "us"})


if __name__ == "__main__":
    unittest.main()
