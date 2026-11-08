import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

from feclora.deployment.enrollment import (
    EnrollmentError, _certificate_identity, enroll_client_certificate, revoke_client_certificate,
)


def config():
    return {
        "schema_version": 1,
        "bind_address": "192.0.2.2",
        "port": 9443,
        "local_identity": "URI:feclora-server",
        "ca_file": "/pki/ca.crt",
        "certificate_file": "/pki/server.crt",
        "private_key_file": "/pki/server.key",
        "client_identity_to_mac": {
            "URI:old-client": "52:54:00:12:34:56",
        },
        "client_minisign_public_keys": {
            "52:54:00:12:34:56": "/pki/old.pub",
        },
        "server_minisign_public_key": "/pki/server.pub",
        "repository": "/repo",
    }


class EnrollmentTests(unittest.TestCase):
    def test_certificate_san_extracts_one_stable_uri_identity(self):
        result = CompletedProcess(
            args=[], returncode=0, stdout="X509v3 Subject Alternative Name:\n    URI:feclora-client-02\n",
            stderr="",
        )
        with patch("feclora.deployment.enrollment.subprocess.run", return_value=result):
            self.assertEqual(
                _certificate_identity("/pki/client.crt"),
                "URI:feclora-client-02",
            )

    def test_certificate_san_rejects_ambiguous_multiple_identities(self):
        result = CompletedProcess(
            args=[], returncode=0,
            stdout="X509v3 Subject Alternative Name:\n    URI:feclora-client-02, DNS:client.example\n",
            stderr="",
        )
        with patch("feclora.deployment.enrollment.subprocess.run", return_value=result):
            with self.assertRaisesRegex(EnrollmentError, "exactly one"):
                _certificate_identity("/pki/client.crt")

    def test_enrollment_rotates_identity_for_same_mac_and_replaces_public_key(self):
        value = config()
        with (
            patch("feclora.deployment.enrollment._load_config", return_value=value),
            patch("feclora.deployment.enrollment._verify_client_certificate",
                  return_value="URI:new-client"),
            patch("feclora.deployment.enrollment._secure_regular_file"),
            patch("feclora.deployment.enrollment._write_config_atomically") as write,
            patch("feclora.deployment.enrollment.load_server_runtime_config"),
        ):
            identity = enroll_client_certificate(
                "/etc/feclora/deployment-server.json", "/pki/new.crt",
                "52:54:00:12:34:56", minisign_public_key="/pki/new.pub",
                confirmation="ENROLL URI:new-client 52:54:00:12:34:56",
            )
        self.assertEqual(identity, "URI:new-client")
        saved = write.call_args.args[1]
        self.assertEqual(saved["client_identity_to_mac"], {
            "URI:new-client": "52:54:00:12:34:56",
        })
        self.assertEqual(saved["client_minisign_public_keys"], {
            "52:54:00:12:34:56": "/pki/new.pub",
        })

    def test_enrollment_rejects_multicast_mac_before_writing_config(self):
        with (
            patch("feclora.deployment.enrollment._load_config", return_value=config()),
            patch("feclora.deployment.enrollment._verify_client_certificate") as verify,
            patch("feclora.deployment.enrollment._write_config_atomically") as write,
        ):
            with self.assertRaisesRegex(EnrollmentError, "unicast hardware"):
                enroll_client_certificate(
                    "/etc/feclora/deployment-server.json", "/pki/client.crt",
                    "01:00:5e:00:00:01",
                    confirmation="ENROLL URI:client 01:00:5e:00:00:01",
                )
        verify.assert_not_called()
        write.assert_not_called()

    def test_enrollment_requires_exact_confirmation(self):
        with (
            patch("feclora.deployment.enrollment._load_config", return_value=config()),
            patch("feclora.deployment.enrollment._verify_client_certificate",
                  return_value="URI:new-client"),
        ):
            with self.assertRaisesRegex(EnrollmentError, "confirmation"):
                enroll_client_certificate(
                    "/etc/feclora/deployment-server.json", "/pki/new.crt",
                    "52:54:00:12:34:56",
                    confirmation="yes",
                )

    def test_revocation_removes_certificate_and_associated_signing_key(self):
        value = config()
        with (
            patch("feclora.deployment.enrollment._load_config", return_value=value),
            patch("feclora.deployment.enrollment._write_config_atomically") as write,
            patch("feclora.deployment.enrollment.load_server_runtime_config"),
        ):
            mac = revoke_client_certificate(
                "/etc/feclora/deployment-server.json", "URI:old-client",
                confirmation="REVOKE URI:old-client",
            )
        self.assertEqual(mac, "52:54:00:12:34:56")
        saved = write.call_args.args[1]
        self.assertEqual(saved["client_identity_to_mac"], {})
        self.assertEqual(saved["client_minisign_public_keys"], {})

    def test_revocation_requires_exact_confirmation(self):
        with patch("feclora.deployment.enrollment._load_config", return_value=config()):
            with self.assertRaisesRegex(EnrollmentError, "confirmation"):
                revoke_client_certificate(
                    "/etc/feclora/deployment-server.json", "URI:old-client",
                    confirmation="yes",
                )


if __name__ == "__main__":
    unittest.main()
