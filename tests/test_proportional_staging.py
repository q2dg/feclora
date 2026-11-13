import gzip
import hashlib
import os
import tempfile
import unittest

from feclora.storage.image_manifest import ImageManifest
from feclora.storage.proportional_staging import (
    ProportionalStagingError,
    stage_verified_raw_disk_image,
)


class VerifiedProportionalStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = os.path.join(self.temp.name, "repository")
        self.staging_root = os.path.join(self.temp.name, "local-stage")
        os.mkdir(self.repository)
        os.mkdir(self.staging_root)
        self.payload = (b"verified whole disk payload\x00" * 128)
        self.stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.repository, "disk.raw.gz"), "wb") as stream:
            stream.write(self.stored)
        with open(os.path.join(self.repository, "table.sfdisk"), "wb") as stream:
            stream.write(b"x")
        self.manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": "stage-test",
            "image_type": "disk",
            "source_size_bytes": len(self.payload),
            "logical_sector_size": 512,
            "partition_table": "gpt",
            "artifacts": [
                {"filename": "disk.raw.gz", "role": "disk-image", "format": "raw",
                 "compression": "gzip", "size_bytes": len(self.stored),
                 "sha256": hashlib.sha256(self.stored).hexdigest()},
                {"filename": "table.sfdisk", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": 1,
                 "sha256": hashlib.sha256(b"x").hexdigest()},
            ],
        })

    def test_creates_private_decoded_copy_and_removes_it_on_context_exit(self):
        original = open(os.path.join(self.repository, "disk.raw.gz"), "rb").read()
        with stage_verified_raw_disk_image(
            self.manifest, self.repository, staging_root=self.staging_root
        ) as staged:
            self.assertEqual(staged.size_bytes, len(self.payload))
            self.assertEqual(staged.sha256, hashlib.sha256(self.payload).hexdigest())
            self.assertEqual(open(staged.path, "rb").read(), self.payload)
            self.assertEqual(os.stat(staged.path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(staged.path)).st_mode & 0o777, 0o700)
            self.assertEqual(os.listdir(self.staging_root), [os.path.basename(os.path.dirname(staged.path))])
        self.assertEqual(os.listdir(self.staging_root), [])
        self.assertEqual(open(os.path.join(self.repository, "disk.raw.gz"), "rb").read(), original)

    def test_rejects_staging_inside_the_source_repository(self):
        with self.assertRaisesRegex(ProportionalStagingError, "outside the image repository"):
            with stage_verified_raw_disk_image(
                self.manifest, self.repository, staging_root=self.repository
            ):
                self.fail("staging must not begin inside the repository")

    def test_rejects_tampered_source_before_yield_and_cleans_stage(self):
        with open(os.path.join(self.repository, "disk.raw.gz"), "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(ProportionalStagingError):
            with stage_verified_raw_disk_image(
                self.manifest, self.repository, staging_root=self.staging_root
            ):
                self.fail("tampered source must never be yielded")
        self.assertEqual(os.listdir(self.staging_root), [])

    def test_rejects_non_disk_manifest(self):
        partition_manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": "partition-test",
            "image_type": "partition",
            "source_size_bytes": len(self.payload),
            "logical_sector_size": 512,
            "partition_table": "none",
            "artifacts": [
                {"filename": "disk.raw.gz", "role": "partition-image", "format": "raw",
                 "compression": "gzip", "size_bytes": len(self.stored),
                 "sha256": hashlib.sha256(self.stored).hexdigest(), "partition_id": "p1"}
            ],
        })
        with self.assertRaisesRegex(ProportionalStagingError, "whole-disk"):
            with stage_verified_raw_disk_image(
                partition_manifest, self.repository, staging_root=self.staging_root
            ):
                self.fail("partition image must not be staged as a whole disk")


if __name__ == "__main__":
    unittest.main()
