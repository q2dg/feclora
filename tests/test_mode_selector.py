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
    @patch("feclora.ui.mode_selector._dialog")
    def test_server_mode_reports_unavailable_and_returns_to_menu(self, dialog, _which):
        from subprocess import CompletedProcess
        dialog.side_effect = [
            CompletedProcess([], 0, "server\n", ""),
            CompletedProcess([], 1, "", ""),
        ]

        self.assertEqual(mode_selector.main(), 0)
        self.assertEqual(dialog.call_count, 2)
        self.assertIn("Server mode not yet implemented", dialog.call_args.args[0])

    @patch("feclora.ui.mode_selector.shutil.which", return_value=None)
    def test_missing_dialog_fails_with_error(self, _which):
        self.assertEqual(mode_selector.main(), 1)


if __name__ == "__main__":
    unittest.main()
