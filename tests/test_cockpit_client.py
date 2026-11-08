import unittest
from unittest.mock import patch

from feclora.deployment.cockpit_client import (
    CockpitEnrollmentError, prepare_client_request, complete_client_enrollment,
)


class CockpitClientTests(unittest.TestCase):
    def test_prepare_restore_only_request_keeps_private_key_local(self):
        params = {
            "client_id": "lab-01",
            "export_directory": "/run/media/test/USB",
            "image_capture": False,
        }
        with patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=False), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value=params["export_directory"]
        ), patch(
            "feclora.deployment.cockpit_client.create_client_csr",
            return_value=("URI:feclora-client-lab-01", "/etc/feclora/pki/client-lab-01.key",
                          "/run/media/test/USB/feclora-lab-01.csr"),
        ):
            result = prepare_client_request(params)
        self.assertEqual(result["identity"], "URI:feclora-client-lab-01")
        self.assertIsNone(result["minisign_public_file"])
        self.assertEqual(result["private_key_stays_local"], "/etc/feclora/pki/client-lab-01.key")

    def test_prepare_rejects_invalid_client_identifier(self):
        with self.assertRaisesRegex(CockpitEnrollmentError, "identifier"):
            prepare_client_request({
                "client_id": "../bad", "export_directory": "/run/media/test/USB",
                "image_capture": False,
            })

    def test_complete_rejects_multicast_mac_before_reading_bundle(self):
        with patch("feclora.deployment.cockpit_client.CONFIG", "/tmp/nonexistent-feclora-client.json"):
            with self.assertRaisesRegex(CockpitEnrollmentError, "unicast"):
                complete_client_enrollment({
                    "client_id": "lab-01", "host": "192.0.2.1",
                    "mac_address": "01:11:22:33:44:55",
                    "bundle_directory": "/run/media/test/USB",
                    "ca_fingerprint": "a" * 64,
                    "server_minisign_sha256": "b" * 64,
                })


if __name__ == "__main__":
    unittest.main()
