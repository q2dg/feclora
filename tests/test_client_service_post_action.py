import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from feclora.deployment.client_service import execute_client_post_action


class ClientPostActionTests(unittest.TestCase):
    def test_none_does_not_invoke_systemctl(self):
        runner = Mock()
        self.assertIsNone(execute_client_post_action("none", runner=runner))
        runner.assert_not_called()

    def test_reboot_uses_fixed_systemctl_argv(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertIsNone(execute_client_post_action("reboot", runner=runner))
        self.assertEqual(runner.call_args.args[0], ["systemctl", "reboot"])

    def test_poweroff_uses_fixed_systemctl_argv(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertIsNone(execute_client_post_action("poweroff", runner=runner))
        self.assertEqual(runner.call_args.args[0], ["systemctl", "poweroff"])

    def test_reports_systemctl_failure_without_arbitrary_command(self):
        runner = Mock(return_value=SimpleNamespace(
            returncode=1, stdout="", stderr="systemd is not running",
        ))
        result = execute_client_post_action("reboot", runner=runner)
        self.assertIn("systemctl reboot failed", result)
        runner.assert_called_once()

    def test_rejects_unknown_action_without_execution(self):
        runner = Mock()
        self.assertIn("unsupported", execute_client_post_action("exec /bin/sh", runner=runner))
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
