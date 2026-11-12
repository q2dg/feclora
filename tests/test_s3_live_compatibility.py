"""Opt-in live compatibility check for AWS S3, R2, Garage and S3-compatible endpoints.

Set FECLORA_S3_TEST_ENDPOINT, FECLORA_S3_TEST_REGION, FECLORA_S3_TEST_BUCKET,
FECLORA_S3_TEST_ACCESS_KEY_ID and FECLORA_S3_TEST_SECRET_ACCESS_KEY. The test
writes only beneath FECLORA_S3_TEST_PREFIX/feclora-compatibility-tests/ and
removes the test objects in a finally block.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from feclora.storage.image_manifest import ImageArtifact, ImageManifest
from feclora.storage.s3_repository import S3ObjectRepository, S3RepositoryConfig


_REQUIRED = (
    "FECLORA_S3_TEST_ENDPOINT",
    "FECLORA_S3_TEST_REGION",
    "FECLORA_S3_TEST_BUCKET",
    "FECLORA_S3_TEST_ACCESS_KEY_ID",
    "FECLORA_S3_TEST_SECRET_ACCESS_KEY",
)


@unittest.skipUnless(all(os.environ.get(key) for key in _REQUIRED),
                     "live S3 credentials/endpoint are not configured")
class LiveS3CompatibilityTests(unittest.TestCase):
    def test_conditional_upload_inventory_download_and_cleanup(self):
        image_id = "compat-" + uuid.uuid4().hex
        prefix = os.environ.get("FECLORA_S3_TEST_PREFIX", "").strip("/")
        prefix = "/".join(item for item in (
            prefix, "feclora-compatibility-tests", uuid.uuid4().hex,
        ) if item)
        config = S3RepositoryConfig(
            endpoint_url=os.environ["FECLORA_S3_TEST_ENDPOINT"],
            region=os.environ["FECLORA_S3_TEST_REGION"],
            bucket=os.environ["FECLORA_S3_TEST_BUCKET"],
            prefix=prefix,
            access_key_id=os.environ["FECLORA_S3_TEST_ACCESS_KEY_ID"],
            secret_access_key=os.environ["FECLORA_S3_TEST_SECRET_ACCESS_KEY"],
        )
        repository = S3ObjectRepository(config)
        keys = []
        try:
            self.assertTrue(repository.check_connection()["bucket_accessible"])
            with tempfile.TemporaryDirectory(prefix="feclora-s3-live-test-") as temporary:
                root = Path(temporary)
                payload = b"Feclora S3 live compatibility probe\n"
                filename = image_id + ".raw"
                (root / filename).write_bytes(payload)
                artifact = ImageArtifact(
                    filename=filename, role="partition-image", format="raw",
                    compression="none", size_bytes=len(payload), partition_id="p1",
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
                manifest = ImageManifest(
                    image_id=image_id, image_type="partition",
                    source_size_bytes=len(payload), logical_sector_size=512,
                    partition_table="none", artifacts=(artifact,),
                )
                (root / (image_id + ".manifest.json")).write_text(
                    manifest.to_json(), encoding="utf-8",
                )
                result = repository.upload_image_set(root, image_id)
                self.assertTrue(result["committed"])
                inventory = repository.list_images()
                self.assertIn(image_id, {item["image_id"] for item in inventory})
                downloaded = root / "downloaded"
                repository.download_image_set(image_id, downloaded)
                self.assertEqual((downloaded / filename).read_bytes(), payload)
                keys = [
                    repository._artifact_key(image_id, filename),
                    repository._manifest_key(image_id),
                ]
                with self.assertRaises(Exception):
                    repository.upload_image_set(root, image_id)
        finally:
            for key in keys:
                repository.client.delete_object(Bucket=config.bucket, Key=key)


if __name__ == "__main__":
    unittest.main()
