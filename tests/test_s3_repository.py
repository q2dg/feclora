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

    def test_inventory_ignores_noncanonical_nested_manifest_keys(self):
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
            manifest_key = "server-a/images/lv-one.manifest.json"
            data, metadata = client.objects.pop(manifest_key)
            client.objects["server-a/images/nested/lv-one.manifest.json"] = (data, metadata)
            self.assertEqual(repository.list_images(), [])

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



    def test_p2v_publication_commits_qcow2_before_metadata_and_lists_verified_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qcow2 = root / "server.qcow2"
            qcow2.write_bytes(b"qcow2-payload")
            digest = hashlib.sha256(qcow2.read_bytes()).hexdigest()
            metadata = {
                "schema_version": 1, "image_id": "server", "format": "qcow2",
                "source_device": "/dev/sda", "virtual_size_bytes": 8192,
                "file_size_bytes": qcow2.stat().st_size, "qcow2_sha256": digest,
                "verified": True, "bootability_note": "Guest boot may require driver changes.",
            }
            sidecar = root / "server.p2v.json"
            import json
            sidecar.write_text(json.dumps(metadata), encoding="utf-8")
            client = _S3()
            repository = S3ObjectRepository(_config(), client=client)
            result = repository.publish_p2v("server", qcow2, sidecar)
            self.assertTrue(result["committed"])
            self.assertEqual([event[1] for event in client.events], [
                "server-a/images/server/server.qcow2", "server-a/images/server.p2v.json",
            ])
            images = repository.list_images()
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0]["image_type"], "virtual_disk")
            self.assertTrue(images[0]["verified"])

    def test_p2v_publication_rejects_changed_qcow2(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qcow2 = root / "server.qcow2"
            qcow2.write_bytes(b"modified")
            sidecar = root / "server.p2v.json"
            import json
            sidecar.write_text(json.dumps({
                "schema_version": 1, "image_id": "server", "format": "qcow2",
                "source_device": "/dev/sda", "virtual_size_bytes": 8192,
                "file_size_bytes": 10, "qcow2_sha256": "0" * 64,
                "verified": True, "bootability_note": "note",
            }), encoding="utf-8")
            repository = S3ObjectRepository(_config(), client=_S3())
            with self.assertRaisesRegex(S3RepositoryError, "does not match"):
                repository.publish_p2v("server", qcow2, sidecar)

    def test_multipart_upload_failure_aborts_incomplete_upload(self):
        class FailingMultipartS3(_S3):
            def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
                raise RuntimeError("simulated part transfer failure")

        with tempfile.TemporaryDirectory() as temporary:
            payload = Path(temporary) / "large-image.raw"
            payload.write_bytes(b"x" * (5 * 1024 * 1024))
            client = FailingMultipartS3()
            repository = S3ObjectRepository(
                _config(), client=client,
                part_size=5 * 1024 * 1024,
                multipart_threshold=5 * 1024 * 1024,
            )
            with self.assertRaisesRegex(S3RepositoryError, "multipart upload failed"):
                repository._put_file(
                    payload, "server-a/images/large-image.raw",
                    hashlib.sha256(payload.read_bytes()).hexdigest(),
                    payload.stat().st_size,
                )
            self.assertEqual(client.uploads, {})
            self.assertEqual(client.objects, {})


if __name__ == "__main__":
    unittest.main()
