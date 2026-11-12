import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage.sftp_image_set import (
    SFTPImageSetError, fetch_image_set, inspect_remote_image_set, publish_image_set,
)


class SFTPImageSetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = b"partition-image-data"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        (self.root / "part-1.img").write_bytes(self.payload)
        document = {
            "schema_version": 1,
            "image_id": "test-image",
            "image_type": "partition",
            "source_size_bytes": len(self.payload),
            "logical_sector_size": 512,
            "partition_table": "none",
            "artifacts": [{
                "filename": "part-1.img", "role": "partition-image", "format": "raw",
                "compression": "none", "size_bytes": len(self.payload), "sha256": self.digest,
                "partition_id": "sda1",
            }],
        }
        self.manifest = self.root / "test-image.manifest.json"
        self.manifest.write_text(json.dumps(document), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _connection(self):
        return {
            "remote_directory": "/images/test-image", "host": "backup.example",
            "username": "backup", "identity_credential": "key-ref",
            "known_hosts_credential": "hosts-ref",
        }

    def _publish(self, transfer, **kwargs):
        return publish_image_set(
            manifest_path=self.manifest, artifact_directory=self.root,
            transfer=transfer, **self._connection(), **kwargs,
        )

    def _remote_files(self):
        return {"manifest.json": self.manifest.read_bytes(), "part-1.img": self.payload}

    def _fetch(self, transfer, **kwargs):
        return fetch_image_set(
            destination_root=self.root, transfer=transfer, **self._connection(), **kwargs,
        )

    def test_uploads_artifacts_then_manifest_commit_marker(self):
        calls = []
        result = self._publish(lambda **kw: calls.append(kw["remote_path"]) or {"completed": True})
        self.assertEqual(calls, ["/images/test-image/part-1.img", "/images/test-image/manifest.json"])
        self.assertTrue(result["published"])
        self.assertEqual(result["publication_marker"], "manifest.json")

    def test_publish_reports_artifact_boundary_progress(self):
        progress = []
        self._publish(lambda **kw: {"completed": True},
                      progress_callback=lambda done, total: progress.append((done, total)))
        total = len(self.payload) + self.manifest.stat().st_size
        self.assertEqual(progress[0], (0, total))
        self.assertEqual(progress[-1], (total, total))

    def test_rejects_artifact_digest_mismatch_before_upload(self):
        (self.root / "part-1.img").write_bytes(b"tampered")
        calls = []
        with self.assertRaises(SFTPImageSetError):
            self._publish(lambda **kw: calls.append(kw))
        self.assertEqual(calls, [])

    def test_fetch_validates_manifest_then_artifact_and_publishes_native_names(self):
        remote = self._remote_files()
        calls = []
        def transfer(**kw):
            name = kw["remote_path"].rsplit("/", 1)[-1]
            calls.append((name, kw.get("expected_sha256")))
            Path(kw["local_path"]).write_bytes(remote[name])
            return {"verified": kw.get("expected_sha256") is not None}
        result = self._fetch(transfer)
        self.assertEqual(calls, [("manifest.json", None), ("part-1.img", self.digest)])
        self.assertTrue((self.root / "test-image.manifest.json").is_file())
        self.assertEqual((self.root / "part-1.img").read_bytes(), self.payload)
        self.assertEqual(result["repository_path"], str(self.root / "test-image.manifest.json"))
        self.assertEqual(list(self.root.glob(".feclora-sftp-incoming-*")), [])

    def test_fetch_rejects_artifact_digest_mismatch_and_cleans_staging(self):
        remote = self._remote_files()
        def transfer(**kw):
            name = kw["remote_path"].rsplit("/", 1)[-1]
            Path(kw["local_path"]).write_bytes(b"tampered" if name == "part-1.img" else remote[name])
            return {"verified": kw.get("expected_sha256") is not None}
        with self.assertRaises(SFTPImageSetError):
            self._fetch(transfer)
        self.assertEqual(list(self.root.glob(".feclora-sftp-incoming-*")), [])

    def test_fetch_never_overwrites_existing_repository_artifact(self):
        remote = self._remote_files()
        marker = self.root / "part-1.img"
        marker.write_bytes(b"keep")
        def transfer(**kw):
            name = kw["remote_path"].rsplit("/", 1)[-1]
            Path(kw["local_path"]).write_bytes(remote[name])
            return {"verified": kw.get("expected_sha256") is not None}
        with self.assertRaises(SFTPImageSetError):
            self._fetch(transfer)
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_fetch_binds_manifest_digest_from_inspection(self):
        remote = self._remote_files()
        requested = []
        def transfer(**kw):
            requested.append(kw["remote_path"])
            name = kw["remote_path"].rsplit("/", 1)[-1]
            Path(kw["local_path"]).write_bytes(remote[name])
            return {"verified": False}
        with self.assertRaisesRegex(SFTPImageSetError, "changed after inspection"):
            self._fetch(transfer, expected_image_id="test-image", expected_manifest_sha256="0" * 64)
        self.assertEqual(requested, ["/images/test-image/manifest.json"])

    def test_inspection_downloads_and_validates_manifest_only(self):
        calls = []
        def transfer(**kw):
            calls.append(kw["remote_path"])
            Path(kw["local_path"]).write_bytes(self.manifest.read_bytes())
            return {"verified": False}
        result = inspect_remote_image_set(transfer=transfer, **self._connection())
        self.assertEqual(calls, ["/images/test-image/manifest.json"])
        self.assertEqual(result["image_id"], "test-image")
        self.assertEqual(result["manifest_sha256"], hashlib.sha256(self.manifest.read_bytes()).hexdigest())

    def test_rejects_artifact_filename_in_manifest_marker_namespace(self):
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        document["artifacts"][0]["filename"] = "another-image.manifest.json"
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(SFTPImageSetError):
            self._publish(lambda **kw: {"completed": True})


if __name__ == "__main__":
    unittest.main()
