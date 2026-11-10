import hashlib
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.sftp_transfer import (
    SFTPTransferError, build_sftp_argv, download_file, list_image_manifests, upload_file,
)


class SFTPTransferTests(unittest.TestCase):
    def test_build_argv_requires_pinned_host_keys_and_key_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "id_ed25519"
            known = Path(temporary) / "known_hosts"
            key.write_text("private", encoding="ascii")
            known.write_text("host-key", encoding="ascii")
            key.chmod(0o600)
            known.chmod(0o644)
            # The test host need not be root; the path policy is covered by
            # the manager credential-store tests. Here we exercise argv policy.
            with patch("feclora.storage.sftp_transfer._credential", side_effect=[str(key), str(known)]):
                argv = build_sftp_argv(
                    host="sftp.example.net", username="backup",
                    identity_file=str(key), known_hosts_file=str(known),
                )
            self.assertIn("-b", argv)
            self.assertIn("StrictHostKeyChecking=yes", argv)
            self.assertIn("-oGlobalKnownHostsFile=/dev/null", argv)
            self.assertIn("-oPasswordAuthentication=no", argv)
            self.assertIn("-oPreferredAuthentications=publickey", argv)
            self.assertIn(f"-oUserKnownHostsFile={known}", argv)
            self.assertIn(f"-oIdentityFile={key}", argv)
            self.assertIn("-F", argv)
            self.assertEqual(argv[-1], "backup@sftp.example.net")

    def test_upload_uses_random_staging_name_then_no_overwrite_hard_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "image.part"
            source.write_bytes(b"image-data")
            calls = []
            def runner(argv, **kwargs):
                calls.append((argv, kwargs))
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch("feclora.storage.sftp_transfer.build_sftp_argv", return_value=["sftp"]):
                result = upload_file(
                    source, "/images/disk.img", host="sftp.example.net",
                    username="backup", identity_file="/key", known_hosts_file="/known",
                    runner=runner,
                )
            self.assertEqual(result["sha256"], hashlib.sha256(b"image-data").hexdigest())
            self.assertTrue(result["published"])
            commands = [call[1]["input"].strip() for call in calls]
            self.assertTrue(commands[0].startswith('put "'))
            self.assertIn(".feclora-", commands[0])
            self.assertTrue(commands[1].startswith("ln "))
            self.assertEqual(commands[1].split()[-1], '"/images/disk.img"')
            self.assertTrue(commands[2].startswith("rm "))
            self.assertEqual(calls[0][0], ["sftp"])

    def test_upload_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.write_text("x", encoding="ascii")
            with self.assertRaises(SFTPTransferError):
                upload_file(
                    source, "/images/../escape", host="sftp.example.net",
                    username="backup", identity_file="/key", known_hosts_file="/known",
                    runner=lambda *_args, **_kwargs: None,
                )

    def test_download_verifies_hash_before_publishing(self):
        payload = b"verified artifact"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "download.img"
            def runner(_argv, **kwargs):
                command = shlex.split(kwargs["input"].strip())
                Path(command[2]).write_bytes(payload)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch("feclora.storage.sftp_transfer.build_sftp_argv", return_value=["sftp"]):
                result = download_file(
                    "/images/disk.img", destination, expected_sha256=digest,
                    host="sftp.example.net", username="backup",
                    identity_file="/key", known_hosts_file="/known", runner=runner,
                )
            self.assertTrue(result["verified"])
            self.assertEqual(destination.read_bytes(), payload)

    def test_download_rejects_hash_mismatch_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "download.img"
            def runner(_argv, **kwargs):
                command = shlex.split(kwargs["input"].strip())
                Path(command[2]).write_bytes(b"tampered")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch("feclora.storage.sftp_transfer.build_sftp_argv", return_value=["sftp"]):
                with self.assertRaisesRegex(SFTPTransferError, "SHA-256"):
                    download_file(
                        "/images/disk.img", destination, expected_sha256="0" * 64,
                        host="sftp.example.net", username="backup",
                        identity_file="/key", known_hosts_file="/known", runner=runner,
                    )
            self.assertFalse(destination.exists())


    def test_download_can_stage_untrusted_metadata_without_claiming_verification(self):
        payload = b'{"schema_version":1}'
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "manifest.json"
            def runner(_argv, **kwargs):
                command = shlex.split(kwargs["input"].strip())
                Path(command[2]).write_bytes(payload)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            with patch("feclora.storage.sftp_transfer.build_sftp_argv", return_value=["sftp"]):
                result = download_file(
                    "/images/manifest.json", destination, expected_sha256=None,
                    host="sftp.example.net", username="backup",
                    identity_file="/key", known_hosts_file="/known", runner=runner,
                )
            self.assertFalse(result["verified"])
            self.assertEqual(destination.read_bytes(), payload)


    def test_lists_only_safe_feclora_manifest_basenames(self):
        def runner(_argv, **kwargs):
            self.assertIn('ls -1 "/images"', kwargs["input"])
            return SimpleNamespace(
                returncode=0,
                stdout="image-01.manifest.json\\n../escape.manifest.json\\nsubdir/evil.manifest.json\\nnotes.txt\\nother.manifest.json\\n",
                stderr="",
            )
        with patch("feclora.storage.sftp_transfer.build_sftp_argv", return_value=["sftp"]):
            names = list_image_manifests(
                "/images", host="sftp.example.net", username="backup",
                identity_file="/key", known_hosts_file="/known", runner=runner,
            )
        self.assertEqual(names, ["image-01.manifest.json", "other.manifest.json"])

    def test_manifest_inventory_rejects_traversal_directory(self):
        with self.assertRaises(SFTPTransferError):
            list_image_manifests(
                "/images/../other", host="sftp.example.net", username="backup",
                identity_file="/key", known_hosts_file="/known",
                runner=lambda *_args, **_kwargs: self.fail("must not connect"),
            )


if __name__ == "__main__":
    unittest.main()
