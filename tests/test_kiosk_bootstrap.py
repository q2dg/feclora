import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feclora.kiosk_bootstrap import (
    BootstrapError, set_admin_password, validate_password,
)


class KioskBootstrapTests(unittest.TestCase):
    def test_password_requires_confirmation_and_minimum_length(self):
        with self.assertRaises(BootstrapError):
            validate_password("short", "short")
        with self.assertRaisesRegex(BootstrapError, "do not match"):
            validate_password("correct horse battery", "different password")
        with self.assertRaises(BootstrapError):
            validate_password(" leading-and-trailing ", " leading-and-trailing ")
        validate_password("correct-horse-battery-2026", "correct-horse-battery-2026")

    def test_password_rejects_chpasswd_delimiters_and_newlines(self):
        for value in ("contains:colon-12345", "contains\nnewline-12345", "contains\rreturn-12345"):
            with self.subTest(value=value), self.assertRaises(BootstrapError):
                validate_password(value, value)

    @patch("feclora.kiosk_bootstrap.grp.getgrnam", return_value=SimpleNamespace(gr_gid=10, gr_mem=["feclora"]))
    @patch("feclora.kiosk_bootstrap.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1000, pw_gid=1000))
    @patch("feclora.kiosk_bootstrap.os.geteuid", return_value=0)
    def test_password_is_sent_only_to_chpasswd_stdin(self, _euid, _account, _wheel):
        runner = Mock(return_value=SimpleNamespace(returncode=0))
        set_admin_password("a-long-private-password", runner=runner)
        runner.assert_called_once()
        args, kwargs = runner.call_args
        self.assertEqual(args[0], ["/usr/sbin/chpasswd"])
        self.assertEqual(kwargs["input"], "feclora:a-long-private-password\n")
        self.assertNotIn("a-long-private-password", " ".join(args[0]))

    @patch("feclora.kiosk_bootstrap.grp.getgrnam", return_value=SimpleNamespace(gr_gid=10, gr_mem=[]))
    @patch("feclora.kiosk_bootstrap.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1000, pw_gid=1000))
    @patch("feclora.kiosk_bootstrap.os.geteuid", return_value=0)
    def test_password_refuses_account_without_wheel_role(self, _euid, _account, _wheel):
        with self.assertRaisesRegex(BootstrapError, "expected role"):
            set_admin_password("a-long-private-password", runner=Mock())

    @patch("feclora.kiosk_bootstrap.grp.getgrnam", return_value=SimpleNamespace(gr_gid=10, gr_mem=["feclora"]))
    @patch("feclora.kiosk_bootstrap.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1000, pw_gid=1000))
    @patch("feclora.kiosk_bootstrap.os.geteuid", return_value=0)
    def test_chpasswd_failure_is_reported_without_command_output(self, _euid, _account, _wheel):
        runner = Mock(return_value=SimpleNamespace(returncode=1, stderr="sensitive detail"))
        with self.assertRaisesRegex(BootstrapError, "Could not set"):
            set_admin_password("a-long-private-password", runner=runner)


if __name__ == "__main__":
    unittest.main()
