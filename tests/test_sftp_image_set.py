import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage.image_security import ImageSecurityError
from feclora.storage.sftp_image_set import SFTPImageSetError, fetch_image_set, publish_image_set


class SFTPImageSetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(mode=0o700)
        self.payload = b"partition image payload"
        (self.artifacts / "part-1.img").write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()
        manifest = {
            "schema_version": 1,
            "image_id": "test-image",
            "image_type": "partition",
            "source_size_bytes": 4096,
            "logical_sector_size": 512,
            "partition_table": "none",
            "artifacts": [{
                "filename": "part-1.img", "role": "partition-image",
                "format": "raw", "compression": "none",
                "size_bytes": len(self.payload), "sha256": self.digest,
                "partition_id": "1",
            }],
        }
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        self.signature = self.root / "manifest.json.minisig"
        self.signature.write_text("untrusted-until-verified", encoding="utf-8")
        self.public_key = self.root / "trusted.pub"
        self.public_key.write_text("trusted public key", encoding="utf-8")

    def _publish(self, transfer, **overrides):
        args = dict(
            manifest_path=self.manifest,
            signature_path=self.signature,
            public_key=self.public_key,
            artifact_directory=self.artifacts,
            remote_directory="/images/test-image",
            host="backup.example",
            username="backup",
            identity_credential="key-ref",
            known_hosts_credential="hosts-ref",
            transfer=transfer,
        )
        args.update(overrides)
        return publish_image_set(**args)

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature")
    def test_uploads_artifacts_then_manifest_then_signature(self, verify):
        calls = []
        def transfer(**kwargs):
            calls.append(kwargs["remote_path"])
            return {"completed": True}
        result = self._publish(transfer)
        verify.assert_called_once()
        self.assertEqual(calls, [
            "/images/test-image/part-1.img",
            "/images/test-image/manifest.json",
            "/images/test-image/manifest.json.minisig",
        ])
        self.assertTrue(result["published"])
        self.assertEqual(result["publication_marker"], "manifest.json.minisig")

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature")
    def test_rejects_artifact_digest_mismatch_before_upload(self, verify):
        (self.artifacts / "part-1.img").write_bytes(b"tampered")
        calls = []
        with self.assertRaises(SFTPImageSetError):
            self._publish(lambda **kwargs: calls.append(kwargs))
        self.assertEqual(calls, [])

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature",
           side_effect=ImageSecurityError("bad signature"))
    def test_rejects_unverified_signature_before_upload(self, verify):
        calls = []
        with self.assertRaises(SFTPImageSetError):
            self._publish(lambda **kwargs: calls.append(kwargs))
        self.assertEqual(calls, [])

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature")
    def test_stops_before_manifest_marker_if_artifact_upload_fails(self, verify):
        calls = []
        def transfer(**kwargs):
            calls.append(kwargs["remote_path"])
            if kwargs["remote_path"].endswith("part-1.img"):
                raise RuntimeError("connection lost")
            return {"completed": True}
        with self.assertRaises(SFTPImageSetError):
            self._publish(transfer)
        self.assertEqual(calls, ["/images/test-image/part-1.img"])


    def _remote_set(self):
        return {
            "manifest.json": self.manifest.read_bytes(),
            "manifest.json.minisig": self.signature.read_bytes(),
            "part-1.img": self.payload,
        }

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature")
    def test_fetch_verifies_metadata_before_artifacts_and_publishes_complete_directory(self, verify):
        remote = self._remote_set()
        calls = []
        def transfer(**kwargs):
            filename = kwargs["remote_path"].rsplit("/", 1)[-1]
            calls.append((filename, kwargs["expected_sha256"], kwargs["allow_unverified_metadata"]))
            Path(kwargs["local_path"]).write_bytes(remote[filename])
            return {"verified": kwargs["expected_sha256"] is not None}
        result = fetch_image_set(
            remote_directory="/images/test-image",
            destination_root=self.root,
            public_key=self.public_key,
            host="backup.example", username="backup",
            identity_credential="key-ref", known_hosts_credential="hosts-ref",
            transfer=transfer,
        )
        verify.assert_called_once()
        self.assertEqual([item[0] for item in calls], [
            "manifest.json", "manifest.json.minisig", "part-1.img",
        ])
        self.assertTrue(calls[0][2])
        self.assertTrue(calls[1][2])
        self.assertEqual(calls[2][1], self.digest)
        self.assertTrue(result["signature_verified"])
        self.assertTrue((Path(result["repository_path"]) / "part-1.img").is_file())
        self.assertTrue((Path(result["repository_path"]) / "manifest.json.minisig").is_file())

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature",
           side_effect=ImageSecurityError("bad signature"))
    def test_fetch_rejects_bad_signature_before_artifact_download(self, verify):
        remote = self._remote_set()
        calls = []
        def transfer(**kwargs):
            filename = kwargs["remote_path"].rsplit("/", 1)[-1]
            calls.append(filename)
            Path(kwargs["local_path"]).write_bytes(remote[filename])
            return {"verified": False}
        fetch = fetch_image_set
        with self.assertRaises(SFTPImageSetError):
            fetch(
                remote_directory="/images/test-image", destination_root=self.root,
                public_key=self.public_key, host="backup.example", username="backup",
                identity_credential="key-ref", known_hosts_credential="hosts-ref",
                transfer=transfer,
            )
        self.assertEqual(calls, ["manifest.json", "manifest.json.minisig"])
        self.assertFalse((self.root / "test-image").exists())

    @patch("feclora.storage.sftp_image_set.verify_manifest_signature")
    def test_fetch_rejects_artifact_digest_mismatch_and_cleans_staging(self, verify):
        remote = self._remote_set()
        def transfer(**kwargs):
            filename = kwargs["remote_path"].rsplit("/", 1)[-1]
            payload = b"tampered" if filename == "part-1.img" else remote[filename]
            Path(kwargs["local_path"]).write_bytes(payload)
            return {"verified": kwargs["expected_sha256"] is not None}
        fetch = fetch_image_set
        with self.assertRaises(SFTPImageSetError):
            fetch(
                remote_directory="/images/test-image", destination_root=self.root,
                public_key=self.public_key, host="backup.example", username="backup",
                identity_credential="key-ref", known_hosts_credential="hosts-ref",
                transfer=transfer,
            )
        self.assertFalse((self.root / "test-image").exists())
        self.assertEqual(list(self.root.glob(".feclora-sftp-incoming-*")), [])


if __name__ == "__main__":
    unittest.main()
