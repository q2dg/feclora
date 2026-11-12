import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.client_ui import _capture_image_security_options, _local_target_confirmation


class ClientUITargetApprovalTests(unittest.TestCase):
    def test_remote_partition_clone_requires_destructive_target_confirmation(self):
        job = SimpleNamespace(operation="clone", target_type="partition")
        phrase, prompt = _local_target_confirmation(job, "/dev/nvme0n1p2", "partition")
        self.assertEqual(phrase, "ERASE /dev/nvme0n1p2")
        self.assertIn("overwrites", prompt)
        self.assertIn("partition", prompt)
        self.assertIn("streamed from the Server", prompt)

    def test_remote_disk_clone_requires_destructive_target_confirmation(self):
        job = SimpleNamespace(operation="clone", target_type="disk")
        phrase, prompt = _local_target_confirmation(job, "/dev/sdb", "disk")
        self.assertEqual(phrase, "ERASE /dev/sdb")
        self.assertIn("whole disk", prompt)

    def test_save_uses_read_only_confirmation(self):
        job = SimpleNamespace(operation="save", target_type="disk")
        phrase, prompt = _local_target_confirmation(job, "/dev/sdb", "disk")
        self.assertEqual(phrase, "READ /dev/sdb")
        self.assertIn("reads", prompt)


class ClientUICaptureSecurityTests(unittest.TestCase):
    def test_no_optional_tools_keeps_plain_capture_available(self):
        config = SimpleNamespace(age_recipients_file=None)
        with patch("feclora.deployment.client_ui.shutil.which", return_value=None), patch(
            "feclora.deployment.client_ui.dialog_app._menu", return_value="none",
        ) as menu:
            result = _capture_image_security_options(config)
        self.assertEqual(result, "")
        self.assertEqual([item[0] for item in menu.call_args.args[2]], ["none"])

    def test_capture_offers_age_only_when_available(self):
        config = SimpleNamespace(age_recipients_file="/pki/recipients.txt")
        with patch("feclora.deployment.client_ui.os.path.isfile", return_value=True), patch(
            "feclora.deployment.client_ui.shutil.which", return_value="/usr/bin/age",
        ), patch("feclora.deployment.client_ui.dialog_app._menu", return_value="age") as menu:
            result = _capture_image_security_options(config)
        self.assertEqual(result, config.age_recipients_file)
        self.assertEqual([item[0] for item in menu.call_args.args[2]], ["none", "age"])


if __name__ == "__main__":
    unittest.main()
