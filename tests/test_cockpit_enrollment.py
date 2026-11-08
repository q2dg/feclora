import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.cockpit_enrollment import (
    CockpitEnrollmentError, inspect_client_request, approve_client_csr, export_server_age_recipients,
)


class CockpitEnrollmentTests(unittest.TestCase):
    def test_media_file_rejects_paths_outside_removable_media(self):
        with tempfile.NamedTemporaryFile() as source:
            with self.assertRaisesRegex(CockpitEnrollmentError, "under /run/media"):
                from feclora.deployment.cockpit_enrollment import _media_file
                _media_file(source.name, "CSR")

    def test_export_server_age_recipients_writes_private_non_overwriting_bundle(self):
        import hashlib
        import os
        import stat
        import tempfile

        payload = ("age1" + "a" * 40 + "\\n").encode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            pki_directory = Path(directory) / "pki"
            pki_directory.mkdir()
            source = pki_directory / "age-recipients.txt"
            source.write_bytes(payload)
            with patch("feclora.deployment.cockpit_enrollment.PKI", str(pki_directory)), patch(
                "feclora.deployment.cockpit_enrollment._media_directory", return_value=directory
            ), patch("feclora.deployment.cockpit_enrollment.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=len(payload)
            )):
                result = export_server_age_recipients({"export_directory": directory})
            self.assertEqual(Path(result["path"]).read_bytes(), payload)
            self.assertEqual(result["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(os.stat(result["path"]).st_mode & 0o777, 0o600)
            with patch("feclora.deployment.cockpit_enrollment.PKI", str(pki_directory)), patch(
                "feclora.deployment.cockpit_enrollment._media_directory", return_value=directory
            ), patch("feclora.deployment.cockpit_enrollment.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=len(payload)
            )):
                with self.assertRaisesRegex(CockpitEnrollmentError, "refusing to overwrite"):
                    export_server_age_recipients({"export_directory": directory})

    def test_inspection_returns_exact_confirmation_without_enrolling(self):
        config = SimpleNamespace(client_identity_to_mac={})
        params = {
            "csr_path": "/run/media/usb/client.csr",
            "age_recipient_path": "/run/media/usb/client.age-recipient",
            "mac_address": "02:11:22:33:44:55",
        }
        with patch("feclora.deployment.cockpit_enrollment._media_file", side_effect=[
            params["csr_path"], params["age_recipient_path"], None
        ]), patch("feclora.deployment.cockpit_enrollment.inspect_client_csr",
                 return_value="URI:feclora-client-lab-01"), patch(
            "feclora.deployment.cockpit_enrollment.Path.read_text",
            return_value="age1" + "a" * 40 + "\n",
        ), patch("feclora.deployment.cockpit_enrollment.load_server_runtime_config",
                 return_value=config):
            result = inspect_client_request(params)
        self.assertEqual(result["confirmation_phrase"], "ENROLL URI:feclora-client-lab-01 02:11:22:33:44:55")
        self.assertEqual(result["image_capture_enabled"], "false")

    def test_approval_issues_certificate_enrolls_and_exports_public_bundle(self):
        config = SimpleNamespace(
            client_identity_to_mac={}, ca_file="/etc/feclora/pki/ca.crt",
            server_minisign_public_key="/etc/feclora/pki/server.pub",
        )
        params = {
            "csr_path": "/run/media/usb/client.csr",
            "age_recipient_path": "/run/media/usb/client.age-recipient",
            "mac_address": "02:11:22:33:44:55",
            "confirmation": "ENROLL URI:feclora-client-lab-01 02:11:22:33:44:55",
        }
        with patch("feclora.deployment.cockpit_enrollment._media_file", side_effect=[
            params["csr_path"], params["age_recipient_path"], None
        ]), patch("feclora.deployment.cockpit_enrollment.inspect_client_csr",
                 return_value="URI:feclora-client-lab-01"), patch(
            "feclora.deployment.cockpit_enrollment.Path.read_text",
            return_value="age1" + "a" * 40 + "\n",
        ), patch("feclora.deployment.cockpit_enrollment.load_server_runtime_config",
                 return_value=config), patch(
            "feclora.deployment.cockpit_enrollment.os.path.lexists", return_value=False
        ), patch("feclora.deployment.cockpit_enrollment.issue_client_certificate"), patch(
            "feclora.deployment.cockpit_enrollment.enroll_client_certificate"
        ) as enroll, patch(
            "feclora.deployment.cockpit_enrollment.register_age_recipient"
        ) as register, patch(
            "feclora.deployment.cockpit_enrollment._atomic_copy"
        ) as copy, patch(
            "feclora.deployment.cockpit_enrollment.ca_fingerprint", return_value="a" * 64
        ), patch("feclora.deployment.cockpit_enrollment.Path.read_bytes", return_value=b"server key"):
            result = approve_client_csr(params)
        self.assertEqual(result["identity"], "URI:feclora-client-lab-01")
        enroll.assert_called_once()
        register.assert_called_once_with("/etc/feclora/pki", "URI:feclora-client-lab-01", "age1" + "a" * 40)
        self.assertEqual(copy.call_count, 3)
        self.assertFalse(result["image_capture_enabled"])


if __name__ == "__main__":
    unittest.main()
