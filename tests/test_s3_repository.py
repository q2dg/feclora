from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from feclora.storage.image_manifest import ImageArtifact, ImageManifest
from feclora.storage.s3_repository import (
    S3ObjectRepository, S3RepositoryConfig, S3RepositoryError,
)


class _NotFound(Exception):
    def __init__(self):
        self.response = {
            "Error": {"Code": "404"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }


class _Paginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, *, Bucket, Prefix):
        yield {"Contents": [
            {"Key": key} for key in sorted(self.client.objects)
            if key.startswith(Prefix)
        ]}


class _S3:
    def __init__(self):
        self.objects = {}
        self.uploads = {}
        self.events = []
        self.next_upload = 0

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()
        data, metadata = self.objects[Key]
        return {"ContentLength": len(data), "Metadata": metadata}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch=None, Metadata=None,
                   ContentLength=None, ContentType=None):
        if IfNoneMatch == "*" and Key in self.objects:
            raise RuntimeError("PreconditionFailed")
        data = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.objects[Key] = (data, Metadata or {})
        self.events.append(("put", Key))
        return {}

    def get_object(self, *, Bucket, Key):
        data, _metadata = self.objects[Key]
        return {"Body": io.BytesIO(data)}

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return _Paginator(self)

    def create_multipart_upload(self, *, Bucket, Key, Metadata):
        self.next_upload += 1
        upload_id = str(self.next_upload)
        self.uploads[upload_id] = {"key": Key, "metadata": Metadata, "parts": {}}
        return {"UploadId": upload_id}

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        data = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.uploads[UploadId]["parts"][PartNumber] = data
        return {"ETag": f'"{PartNumber}"'}

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload, IfNoneMatch):
        if IfNoneMatch == "*" and Key in self.objects:
            raise RuntimeError("PreconditionFailed")
        upload = self.uploads.pop(UploadId)
        data = b"".join(upload["parts"][number] for number in sorted(upload["parts"]))
        self.objects[Key] = (data, upload["metadata"])
        self.events.append(("complete", Key))
        return {}

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.uploads.pop(UploadId, None)


def _config(**changes):
    values = {
        "endpoint_url": "https://objects.example.test",
        "region": "auto",
        "bucket": "feclora-images",
        "prefix": "server-a/images",
        "access_key_id": "0123456789ABCDEFGHIJ",
        "secret_access_key": "test-secret-key-value",
        "read_only": False,
    }
    values.update(changes)
    return S3RepositoryConfig(**values)


class S3RepositoryTests(unittest.TestCase):
    def test_config_requires_https_endpoint_and_safe_prefix(self):
        with self.assertRaises(S3RepositoryError):
            _config(endpoint_url="http://objects.example.test")
        with self.assertRaises(S3RepositoryError):
            _config(prefix="../other-bucket")

    def test_upload_publishes_manifest_after_verified_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"test image payload"
            (root / "lv-one.raw").write_bytes(payload)
            artifact = ImageArtifact(
                filename="lv-one.raw", role="partition-image", format="raw",
                compression="none", size_bytes=len(payload), partition_id="p1",
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            manifest = ImageManifest(
                image_id="lv-one", image_type="partition",
                source_size_bytes=len(payload), logical_sector_size=512,
                partition_table="none", artifacts=(artifact,),
            )
            (root / "lv-one.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
            client = _S3()
            repository = S3ObjectRepository(_config(), client=client)
            result = repository.upload_image_set(root, "lv-one")
            self.assertTrue(result["committed"])
            self.assertEqual(
                [event[1] for event in client.events],
                ["server-a/images/lv-one/lv-one.raw", "server-a/images/lv-one.manifest.json"],
            )
            self.assertEqual(len(repository.list_images()), 1)

            destination = root / "restore"
            downloaded_manifest = repository.download_image_set("lv-one", destination)
            self.assertEqual(downloaded_manifest.name, "lv-one.manifest.json")
            self.assertEqual((destination / "lv-one.raw").read_bytes(), payload)

    def test_upload_refuses_existing_manifest_and_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"image"
            (root / "lv-one.raw").write_bytes(payload)
            artifact = ImageArtifact(
                filename="lv-one.raw", role="partition-image", format="raw",
                compression="none", size_bytes=len(payload), partition_id="p1",
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            manifest = ImageManifest(
                image_id="lv-one", image_type="partition",
                source_size_bytes=len(payload), logical_sector_size=512,
                partition_table="none", artifacts=(artifact,),
            )
            (root / "lv-one.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
            client = _S3()
            repository = S3ObjectRepository(_config(), client=client)
            repository.upload_image_set(root, "lv-one")
            with self.assertRaises(S3RepositoryError):
                repository.upload_image_set(root, "lv-one")
            read_only = S3ObjectRepository(_config(read_only=True), client=_S3())
            with self.assertRaisesRegex(S3RepositoryError, "read-only"):
                read_only.upload_image_set(root, "lv-one")


if __name__ == "__main__":
    unittest.main()
