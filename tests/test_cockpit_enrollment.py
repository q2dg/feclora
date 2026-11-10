import tempfile
import stat
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

        payload = ("age1" + "a" * 40 + "\n").encode("ascii")
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
        self.assertEqual(result["image_signing_enabled"], "false")

    def test_inspection_recognizes_existing_identity_as_key_preserving_renewal(self):
        identity = "URI:feclora-client-lab-01"
        recipient = "age1" + "a" * 40
        config = SimpleNamespace(
            client_identity_to_mac={identity: "02:11:22:33:44:55"},
            client_minisign_public_keys={},
        )
        params = {
            "csr_path": "/run/media/usb/feclora-lab-01-renewal.csr",
            "age_recipient_path": "/run/media/usb/feclora-lab-01-renewal.age-recipient",
            "mac_address": "02:11:22:33:44:55", "renewal": True,
        }
        with patch("feclora.deployment.cockpit_enrollment._media_file", side_effect=[
            params["csr_path"], params["age_recipient_path"], None
        ]), patch("feclora.deployment.cockpit_enrollment.inspect_client_csr", return_value=identity), patch(
            "feclora.deployment.cockpit_enrollment.Path.read_text", return_value=recipient
        ), patch("feclora.deployment.cockpit_enrollment.os.lstat", return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0
        )), patch("feclora.deployment.cockpit_enrollment.load_server_runtime_config", return_value=config), patch(
            "feclora.deployment.cockpit_enrollment._verify_client_csr_pin"
        ):
            result = inspect_client_request(params)
        self.assertEqual(result["confirmation_phrase"], f"RENEW {identity}")
        self.assertEqual(result["renewal"], "true")

    def test_renewal_approval_preserves_existing_trust_mappings(self):
        import stat
        identity = "URI:feclora-client-lab-01"
        recipient = "age1" + "a" * 40
        config = SimpleNamespace(
            client_identity_to_mac={identity: "02:11:22:33:44:55"},
            client_minisign_public_keys={},
            ca_file="/etc/feclora/pki/ca.crt",
            server_minisign_public_key="/etc/feclora/pki/server.pub",
        )
        params = {
            "csr_path": "/run/media/usb/feclora-lab-01-renewal.csr",
            "age_recipient_path": "/run/media/usb/feclora-lab-01-renewal.age-recipient",
            "mac_address": "02:11:22:33:44:55",
            "confirmation": f"RENEW {identity}", "renewal": True,
        }
        with patch("feclora.deployment.cockpit_enrollment._media_file", side_effect=[
            params["csr_path"], params["age_recipient_path"], None
        ]), patch("feclora.deployment.cockpit_enrollment.inspect_client_csr", return_value=identity), patch(
            "feclora.deployment.cockpit_enrollment.Path.read_text", return_value=recipient
        ), patch("feclora.deployment.cockpit_enrollment.os.lstat", return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0
        )), patch("feclora.deployment.cockpit_enrollment.load_server_runtime_config", return_value=config), patch(
            "feclora.deployment.cockpit_enrollment._verify_client_csr_pin"
        ), patch("feclora.deployment.cockpit_enrollment.os.path.isfile", return_value=True), patch(
            "feclora.deployment.cockpit_enrollment.os.path.lexists", return_value=False
        ), patch("feclora.deployment.cockpit_enrollment.issue_client_certificate") as issue, patch(
            "feclora.deployment.cockpit_enrollment._atomic_copy"
        ) as copy, patch("feclora.deployment.cockpit_enrollment.ca_fingerprint", return_value="a" * 64), patch(
            "feclora.deployment.cockpit_enrollment.Path.read_bytes", return_value=b"server key"
        ):
            result = approve_client_csr(params)
        issue.assert_called_once()
        self.assertEqual(copy.call_count, 3)
        self.assertTrue(result["renewal"])
        self.assertEqual(result["identity"], identity)

    def test_renewal_rejects_csr_with_different_public_key_pin(self):
        from pathlib import Path
        pin = Path("/etc/feclora/pki/client-certificate-pins/lab-01.sha256")
        with patch("feclora.deployment.cockpit_enrollment._client_pin_path", return_value=pin), patch(
            "feclora.deployment.cockpit_enrollment.os.lstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0
            )
        ), patch("feclora.deployment.cockpit_enrollment.Path.read_text", return_value="a" * 64), patch(
            "feclora.deployment.cockpit_enrollment._public_key_fingerprint", return_value="b" * 64
        ):
            from feclora.deployment.cockpit_enrollment import _verify_client_csr_pin
            with self.assertRaisesRegex(CockpitEnrollmentError, "does not match the TLS key pinned"):
                _verify_client_csr_pin("URI:feclora-client-lab-01", "/run/media/usb/renewal.csr")

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
            "feclora.deployment.cockpit_enrollment.os.path.isfile", return_value=True
        ), patch("feclora.deployment.cockpit_enrollment.os.path.lexists", return_value=False
        ), patch("feclora.deployment.cockpit_enrollment.issue_client_certificate"), patch(
            "feclora.deployment.cockpit_enrollment.enroll_client_certificate"
        ) as enroll, patch(
            "feclora.deployment.cockpit_enrollment.register_age_recipient"
        ) as register, patch(
            "feclora.deployment.cockpit_enrollment._store_client_certificate_pin"
        ) as store_pin, patch("feclora.deployment.cockpit_enrollment._atomic_copy") as copy, patch(
            "feclora.deployment.cockpit_enrollment.ca_fingerprint", return_value="a" * 64
        ), patch("feclora.deployment.cockpit_enrollment.Path.read_bytes", return_value=b"server key"):
            result = approve_client_csr(params)
        self.assertEqual(result["identity"], "URI:feclora-client-lab-01")
        enroll.assert_called_once()
        register.assert_called_once_with("/etc/feclora/pki", "URI:feclora-client-lab-01", "age1" + "a" * 40)
        self.assertEqual(copy.call_count, 3)
        store_pin.assert_called_once()
        self.assertFalse(result["image_signing_enabled"])


    def test_inspection_accepts_tls_only_csr_without_age_or_minisign_material(self):
        config = SimpleNamespace(
            client_identity_to_mac={}, client_minisign_public_keys={},
        )
        params = {
            "csr_path": "/run/media/usb/client.csr",
            "mac_address": "02:11:22:33:44:55",
        }
        with patch("feclora.deployment.cockpit_enrollment._media_file", side_effect=[
            params["csr_path"], None, None,
        ]), patch("feclora.deployment.cockpit_enrollment.inspect_client_csr",
                 return_value="URI:feclora-client-lab-01"), patch(
            "feclora.deployment.cockpit_enrollment.load_server_runtime_config",
            return_value=config,
        ):
            result = inspect_client_request(params)
        self.assertEqual(result["confirmation_phrase"], "ENROLL URI:feclora-client-lab-01 02:11:22:33:44:55")
        self.assertEqual(result["age_encryption_enabled"], "false")
        self.assertEqual(result["image_signing_enabled"], "false")

    def test_approval_completes_tls_only_enrollment_without_optional_image_keys(self):
        config = SimpleNamespace(
            client_identity_to_mac={}, client_minisign_public_keys={},
            ca_file="/etc/feclora/pki/ca.crt", server_minisign_public_key=None,
        )
        params = {
            "csr_path": "/run/media/usb/client.csr",
            "mac_address": "02:11:22:33:44:55",
            "confirmation": "ENROLL URI:feclora-client-lab-01 02:11:22:33:44:55",
        }
        with patch("feclora.deployment.cockpit_enrollment._media_file", side_effect=[
            params["csr_path"], None, None,
        ]), patch("feclora.deployment.cockpit_enrollment.inspect_client_csr",
                 return_value="URI:feclora-client-lab-01"), patch(
            "feclora.deployment.cockpit_enrollment.load_server_runtime_config",
            return_value=config,
        ), patch("feclora.deployment.cockpit_enrollment.os.path.isfile", return_value=False), patch(
            "feclora.deployment.cockpit_enrollment.os.path.lexists", return_value=False,
        ), patch("feclora.deployment.cockpit_enrollment.issue_client_certificate"), patch(
            "feclora.deployment.cockpit_enrollment._store_client_certificate_pin",
        ), patch("feclora.deployment.cockpit_enrollment.register_age_recipient") as register, patch(
            "feclora.deployment.cockpit_enrollment.enroll_client_certificate",
        ) as enroll, patch("feclora.deployment.cockpit_enrollment._atomic_copy") as copy, patch(
            "feclora.deployment.cockpit_enrollment.ca_fingerprint", return_value="a" * 64,
        ):
            result = approve_client_csr(params)
        register.assert_not_called()
        enroll.assert_called_once()
        self.assertEqual(copy.call_count, 1)
        self.assertIsNone(result["server_minisign_sha256"])
        self.assertFalse(result["age_encryption_enabled"])
        self.assertFalse(result["image_signing_enabled"])


if __name__ == "__main__":
    unittest.main()
