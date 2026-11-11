import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.cockpit_client import (
    CockpitEnrollmentError, prepare_client_request, complete_client_enrollment, refresh_client_age_recipients, export_pxe_client_identity,
    prepare_client_renewal, complete_client_renewal,
)


class CockpitClientTests(unittest.TestCase):
    def test_export_pxe_identity_copies_private_material_to_private_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            media.mkdir()
            pki = root / "pki"
            pki.mkdir()
            paths = {}
            for name, private in (("ca.crt", False), ("client.crt", False), ("client.key", True)):
                path = pki / name
                path.write_text("material-" + name, encoding="utf-8")
                path.chmod(0o600 if private else 0o644)
                paths[name] = str(path)
            config_path = root / "deployment-client.json"
            config = {
                "schema_version": 1, "host": "192.0.2.10", "port": 9443,
                "local_identity": "URI:feclora-client-lab", "server_identity": "URI:feclora-server",
                "mac_address": "52:54:00:12:34:56", "ca_file": paths["ca.crt"],
                "certificate_file": paths["client.crt"], "private_key_file": paths["client.key"],
                "trusted_server_public_key": None, "local_minisign_secret_key": None,
                "local_minisign_public_key": None, "age_identity_file": None,
                "age_recipients_file": None, "repository": "/var/lib/feclora/images",
            }
            config_path.write_text(__import__("json").dumps(config), encoding="utf-8")
            runtime = SimpleNamespace(
                local_identity=config["local_identity"], ca_file=paths["ca.crt"],
                certificate_file=paths["client.crt"], private_key_file=paths["client.key"],
                trusted_server_public_key=None, local_minisign_secret_key=None,
                local_minisign_public_key=None, age_identity_file=None, age_recipients_file=None,
            )
            with patch("feclora.deployment.cockpit_client.CONFIG", str(config_path)), patch(
                "feclora.deployment.cockpit_client.REPOSITORY", "/var/lib/feclora/images"
            ), patch("feclora.deployment.cockpit_client.load_client_runtime_config", return_value=runtime), patch(
                "feclora.deployment.cockpit_client._mounted_media_directory", return_value=str(media)
            ), patch("feclora.deployment.cockpit_client._require_pxe_identity_media"), patch(
                "feclora.network.remote_clone_protocol.create_mutual_tls_context"
            ):
                result = export_pxe_client_identity({"export_directory": str(media)})
            exported = media / "feclora-client-identity"
            self.assertEqual(result["identity"], "URI:feclora-client-lab")
            self.assertEqual((exported / "client.key").stat().st_mode & 0o777, 0o600)
            self.assertEqual((exported / "deployment-client.json").stat().st_mode & 0o777, 0o600)
            rewritten = __import__("json").loads((exported / "deployment-client.json").read_text())
            self.assertEqual(rewritten["private_key_file"], "/mnt/feclora-pxe-identity/feclora-client-identity/client.key")
            self.assertEqual(rewritten["ca_file"], "/mnt/feclora-pxe-identity/feclora-client-identity/ca.crt")
            self.assertFalse((exported / "client.key").is_symlink())

    def test_export_pxe_identity_refuses_existing_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory)
            (media / "feclora-client-identity").mkdir()
            with patch("feclora.deployment.cockpit_client.load_client_runtime_config", return_value=SimpleNamespace()), patch(
                "feclora.deployment.cockpit_client._mounted_media_directory", return_value=str(media)
            ), patch("feclora.deployment.cockpit_client._require_pxe_identity_media"):
                with self.assertRaisesRegex(CockpitEnrollmentError, "already exists"):
                    export_pxe_client_identity({"export_directory": str(media)})

    def test_prepare_restore_only_request_keeps_private_key_local(self):
        params = {
            "client_id": "lab-01",
            "export_directory": "/run/media/test/USB",
            "image_signing": False,
            "age_encryption": False,
        }
        with patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=False), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value=params["export_directory"]
        ), patch("feclora.deployment.cockpit_client.shutil.which", return_value="/usr/bin/age-keygen") as which, patch(
            "feclora.deployment.cockpit_client.create_client_csr",
            return_value=("URI:feclora-client-lab-01", "/etc/feclora/pki/client-lab-01.key",
                          "/run/media/test/USB/feclora-lab-01.csr"),
        ) as create:
            result = prepare_client_request(params)
        which.assert_not_called()
        create.assert_called_once_with(
            "/etc/feclora/pki", params["export_directory"], "lab-01", age_keygen=None,
        )
        self.assertEqual(result["identity"], "URI:feclora-client-lab-01")
        self.assertIsNone(result["minisign_public_file"])
        self.assertEqual(result["private_key_stays_local"], "/etc/feclora/pki/client-lab-01.key")

    def test_prepare_client_request_provisions_age_only_when_explicitly_selected(self):
        params = {
            "client_id": "lab-03", "export_directory": "/run/media/test/USB",
            "image_signing": False, "age_encryption": True,
        }
        with patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=False), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value=params["export_directory"]
        ), patch("feclora.deployment.cockpit_client.shutil.which", return_value="/usr/bin/age-keygen"), patch(
            "feclora.deployment.cockpit_client.create_client_csr",
            return_value=("URI:feclora-client-lab-03", "/etc/feclora/pki/client-lab-03.key",
                          "/run/media/test/USB/feclora-lab-03.csr"),
        ) as create:
            prepare_client_request(params)
        create.assert_called_once_with(
            "/etc/feclora/pki", params["export_directory"], "lab-03",
            age_keygen="/usr/bin/age-keygen",
        )

    def test_prepare_client_request_fails_early_if_requested_age_tool_is_missing(self):
        params = {
            "client_id": "lab-04", "export_directory": "/run/media/test/USB",
            "image_signing": False, "age_encryption": True,
        }
        with patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=False), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value=params["export_directory"]
        ), patch("feclora.deployment.cockpit_client.shutil.which", return_value=None), patch(
            "feclora.deployment.cockpit_client.create_client_csr"
        ) as create:
            with self.assertRaisesRegex(CockpitEnrollmentError, "age-keygen is required only"):
                prepare_client_request(params)
        create.assert_not_called()

    def test_prepare_client_request_fails_early_if_requested_minisign_tool_is_missing(self):
        params = {
            "client_id": "lab-05", "export_directory": "/run/media/test/USB",
            "image_signing": True, "age_encryption": False,
        }
        with patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=False), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value=params["export_directory"]
        ), patch("feclora.deployment.cockpit_client.shutil.which", return_value=None), patch(
            "feclora.deployment.cockpit_client.create_client_csr"
        ) as create:
            with self.assertRaisesRegex(CockpitEnrollmentError, "minisign is required only"):
                prepare_client_request(params)
        create.assert_not_called()

    def test_prepare_client_renewal_reuses_existing_tls_key_and_exports_only_public_material(self):
        config = SimpleNamespace(
            local_identity="URI:feclora-client-lab-01",
            private_key_file="/etc/feclora/pki/client.key",
            local_minisign_public_key=None,
            age_identity_file="/etc/feclora/pki/client-lab-01.age",
        )
        with patch("feclora.deployment.cockpit_client.load_client_runtime_config", return_value=config), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value="/run/media/test/USB"
        ), patch("feclora.deployment.cockpit_client.os.lstat", return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0
        )), patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=True), patch(
            "feclora.deployment.cockpit_client.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout=b"same-public-key"
            )
        ), patch("feclora.deployment.cockpit_client.create_client_csr", return_value=(
            "URI:feclora-client-lab-01", config.private_key_file,
            "/run/media/test/USB/feclora-lab-01-renewal.csr",
        )) as create:
            result = prepare_client_renewal({"export_directory": "/run/media/test/USB"})
        create.assert_called_once_with(
            "/etc/feclora/pki", "/run/media/test/USB", "lab-01",
            reuse_existing_key=True, age_keygen=None,
        )
        self.assertEqual(result["identity"], config.local_identity)
        self.assertIsNone(result["minisign_public_file"])

    def test_prepare_client_renewal_does_not_enable_age_when_not_configured(self):
        config = SimpleNamespace(
            local_identity="URI:feclora-client-lab-02",
            private_key_file="/etc/feclora/pki/client.key",
            local_minisign_public_key=None,
            age_identity_file=None,
        )
        with patch("feclora.deployment.cockpit_client.load_client_runtime_config", return_value=config), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value="/run/media/test/USB"
        ), patch("feclora.deployment.cockpit_client.os.lstat", return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0
        )), patch("feclora.deployment.cockpit_client.os.path.lexists", return_value=False), patch(
            "feclora.deployment.cockpit_client.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout=b"same-public-key"
            )
        ), patch("feclora.deployment.cockpit_client.shutil.which", return_value="/usr/bin/age-keygen"), patch(
            "feclora.deployment.cockpit_client.create_client_csr", return_value=(
                "URI:feclora-client-lab-02", config.private_key_file,
                "/run/media/test/USB/feclora-lab-02-renewal.csr",
            )
        ) as create:
            prepare_client_renewal({"export_directory": "/run/media/test/USB"})
        create.assert_called_once_with(
            "/etc/feclora/pki", "/run/media/test/USB", "lab-02",
            reuse_existing_key=True, age_keygen=None,
        )

    def test_prepare_rejects_invalid_client_identifier(self):
        with self.assertRaisesRegex(CockpitEnrollmentError, "identifier"):
            prepare_client_request({
                "client_id": "../bad", "export_directory": "/run/media/test/USB",
                "image_signing": False, "age_encryption": False,
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

    def test_complete_client_renewal_installs_only_after_trust_checks(self):
        recipient = "age1" + "a" * 40
        config = SimpleNamespace(
            local_identity="URI:feclora-client-lab-01",
            private_key_file="/etc/feclora/pki/client.key",
            certificate_file="/etc/feclora/pki/client.crt",
            ca_file="/etc/feclora/pki/ca.crt",
            age_identity_file="/etc/feclora/pki/client-lab-01.age",
            local_minisign_secret_key=None,
            local_minisign_public_key=None,
        )
        installed_config = config
        bundle_paths = [
            "/run/media/test/USB/feclora-lab-01-renewal.crt",
            "/run/media/test/USB/ca-renewal.crt",
            "/run/media/test/USB/server-renewal.pub",
            "/run/media/test/USB/age-recipients-renewal.txt",
        ]
        with patch("feclora.deployment.cockpit_client.load_client_runtime_config", side_effect=[config, installed_config]), patch(
            "feclora.deployment.cockpit_client._mounted_media_directory", return_value="/run/media/test/USB"
        ), patch("feclora.deployment.cockpit_client._bundle_file", side_effect=bundle_paths), patch(
            "feclora.deployment.cockpit_client.Path.read_bytes", return_value=b"server public key"
        ), patch("feclora.deployment.cockpit_client.Path.read_text", return_value=recipient + "\n"), patch(
            "feclora.deployment.cockpit_client.json.loads", return_value={
                "trusted_server_public_key": None, "age_recipients_file": None,
            }
        ), patch("feclora.deployment.cockpit_client.shutil.which", return_value="/usr/bin/age-keygen"), patch(
            "feclora.deployment.cockpit_client.subprocess.run", return_value=SimpleNamespace(
                returncode=0, stdout=recipient + "\n"
            )
        ), patch("feclora.deployment.cockpit_client.os.lstat", return_value=SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=0
        )), patch("feclora.deployment.cockpit_client.install_client_certificate", return_value={
            "certificate_file": "/etc/feclora/pki/client.crt",
        }) as install, patch("feclora.deployment.cockpit_client._atomic_copy") as copy, patch(
            "feclora.deployment.cockpit_client._write_config"
        ):
            result = complete_client_renewal({
                "bundle_directory": "/run/media/test/USB",
                "ca_fingerprint": "a" * 64,
                "server_minisign_sha256": __import__("hashlib").sha256(b"server public key").hexdigest(),
            })
        install.assert_called_once()
        self.assertEqual(copy.call_count, 2)
        self.assertEqual(result["identity"], config.local_identity)
        self.assertIn("optional age and minisign material", result["message"])

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
