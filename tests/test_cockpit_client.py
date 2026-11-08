import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.cockpit_client import (
    CockpitEnrollmentError, prepare_client_request, complete_client_enrollment, refresh_client_age_recipients,
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

    def test_refresh_client_age_recipients_verifies_own_identity_and_atomically_installs(self):
        recipient = "age1" + "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "usb"
            media.mkdir()
            source = media / "age-recipients.txt"
            source.write_text(recipient + "\n", encoding="ascii")
            identity = root / "client.age"
            identity.write_text("private identity stays local", encoding="ascii")
            destination = root / "installed-recipients.txt"
            config = SimpleNamespace(
                age_identity_file=str(identity),
                age_recipients_file=str(destination),
            )
            real_lstat = os.lstat
            def lstat(path):
                if os.fspath(path) == str(identity):
                    return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0)
                if os.fspath(path) == str(root):
                    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
                return real_lstat(path)
            with patch("feclora.deployment.cockpit_client._mounted_media_directory", return_value=str(media)), patch(
                "feclora.deployment.cockpit_client.load_client_runtime_config", return_value=config
            ), patch("feclora.deployment.cockpit_client.os.lstat", side_effect=lstat), patch(
                "feclora.deployment.cockpit_client.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=recipient + "\n"),
            ):
                result = refresh_client_age_recipients({"inventory_path": str(source)})
            self.assertEqual(destination.read_text(encoding="ascii"), recipient + "\n")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["recipient_count"], 1)
            self.assertEqual(identity.read_text(encoding="ascii"), "private identity stays local")
            source.write_text("age1" + "b" * 40 + "\n", encoding="ascii")
            with patch("feclora.deployment.cockpit_client._mounted_media_directory", return_value=str(media)), patch(
                "feclora.deployment.cockpit_client.load_client_runtime_config", return_value=config
            ), patch("feclora.deployment.cockpit_client.os.lstat", side_effect=lstat), patch(
                "feclora.deployment.cockpit_client.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=recipient + "\n"),
            ):
                with self.assertRaisesRegex(CockpitEnrollmentError, "does not contain this Client"):
                    refresh_client_age_recipients({"inventory_path": str(source)})
            self.assertEqual(destination.read_text(encoding="ascii"), recipient + "\n")

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
