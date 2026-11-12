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
    def test_no_optional_tools_keeps_unprotected_capture_available(self):
        config = SimpleNamespace(
            age_recipients_file=None,
            local_minisign_secret_key=None,
            local_minisign_public_key=None,
        )
        with patch("feclora.deployment.client_ui.shutil.which", return_value=None), patch(
            "feclora.deployment.client_ui.dialog_app._menu", return_value="none",
        ) as menu:
            result = _capture_image_security_options(config)
        self.assertEqual(result, (None, None))
        choices = menu.call_args.args[2]
        self.assertEqual([item[0] for item in choices], ["none"])

    def test_capture_offers_only_available_protection_modes(self):
        config = SimpleNamespace(
            age_recipients_file="/pki/recipients.txt",
            local_minisign_secret_key="/pki/client.minisign.key",
            local_minisign_public_key="/pki/client.minisign.pub",
        )
        with patch("feclora.deployment.client_ui.os.path.isfile", return_value=True), patch(
            "feclora.deployment.client_ui.shutil.which",
            side_effect=lambda name: "/usr/bin/" + name,
        ), patch("feclora.deployment.client_ui.dialog_app._menu", return_value="both") as menu:
            result = _capture_image_security_options(config)
        self.assertEqual(result, (config.age_recipients_file, config.local_minisign_secret_key))
        choices = menu.call_args.args[2]
        self.assertEqual([item[0] for item in choices], ["none", "age", "minisign", "both"])


if __name__ == "__main__":
    unittest.main()
