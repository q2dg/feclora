import unittest
from unittest.mock import patch

from feclora.ui import mode_selector


class ModeSelectorTests(unittest.TestCase):
    @patch("feclora.ui.mode_selector.shutil.which", return_value="/usr/bin/dialog")
    @patch("feclora.ui.mode_selector.run_live", return_value=7)
    @patch("feclora.ui.mode_selector._dialog")
    def test_live_mode_dispatches_to_local_rescue(self, dialog, run_live, _which):
        dialog.return_value.returncode = 0
        dialog.return_value.stdout = "live\n"

        self.assertEqual(mode_selector.main(), 7)
        run_live.assert_called_once_with()

    @patch("feclora.ui.mode_selector.shutil.which", return_value="/usr/bin/dialog")
    @patch("feclora.ui.mode_selector.run_server_ui")
    @patch("feclora.ui.mode_selector._dialog")
    def test_server_mode_dispatches_to_server_ui(self, dialog, run_server, _which):
        from subprocess import CompletedProcess
        dialog.side_effect = [
            CompletedProcess([], 0, "server\n", ""),
            CompletedProcess([], 1, "", ""),
        ]
        self.assertEqual(mode_selector.main(), 0)
        run_server.assert_called_once_with()

    @patch("feclora.ui.mode_selector.shutil.which", return_value="/usr/bin/loadkeys")
    @patch("feclora.ui.mode_selector.subprocess.run")
    @patch("feclora.ui.mode_selector._dialog")
    def test_keyboard_layout_applies_allowlisted_layout(self, dialog, run, _which):
        from subprocess import CompletedProcess
        dialog.side_effect = [
            CompletedProcess([], 0, "es\n", ""),
            CompletedProcess([], 0, "", ""),
        ]
        run.return_value = CompletedProcess([], 0, "", "")
        mode_selector._select_keyboard()
        run.assert_called_once_with(
            ["/usr/bin/loadkeys", "es"], check=False,
            capture_output=True, text=True, timeout=15,
        )

    @patch("feclora.ui.mode_selector.shutil.which", return_value=None)
    def test_missing_dialog_fails_with_error(self, _which):
        self.assertEqual(mode_selector.main(), 1)


if __name__ == "__main__":
    unittest.main()
