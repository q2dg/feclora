import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage.image_security import ImageSecurityError
from feclora.storage.sftp_image_set import SFTPImageSetError, publish_image_set


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


if __name__ == "__main__":
    unittest.main()
