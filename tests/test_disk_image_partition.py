import gzip
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from feclora.storage.disk_image_partition import DiskImagePartitionError, extract_partition_image
from feclora.storage.image_manifest import ImageManifest


class DiskImagePartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = bytes(range(256)) * 8200
        self.stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.temp.name, "source.disk.gz"), "wb") as stream:
            stream.write(self.stored)
        self.table = (
            "label: gpt\n"
            "sector-size: 512\n"
            "unit: sectors\n"
            "/dev/sda1 : start=2048, size=4, type=\"Linux filesystem\", uuid=\"aaaa-bbbb\", name=\"root fs\"\n"
            "/dev/sda2 : start=4096, size=4, type=\"Linux filesystem\", uuid=\"cccc-dddd\"\n"
        )
        table_bytes = self.table.encode()
        with open(os.path.join(self.temp.name, "source.sfdisk"), "wb") as stream:
            stream.write(table_bytes)
        manifest = {
            "schema_version": 1, "image_id": "source-disk", "image_type": "disk",
            "source_size_bytes": len(self.payload), "logical_sector_size": 512,
            "partition_table": "gpt",
            "artifacts": [
                {"filename": "source.disk.gz", "role": "disk-image", "format": "raw",
                 "compression": "gzip", "size_bytes": len(self.stored),
                 "sha256": hashlib.sha256(self.stored).hexdigest()},
                {"filename": "source.sfdisk", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": len(table_bytes),
                 "sha256": hashlib.sha256(table_bytes).hexdigest()},
            ],
        }
        self.manifest = "source.manifest.json"
        with open(os.path.join(self.temp.name, self.manifest), "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)

    def test_extracts_selected_partition_and_publishes_manifest(self):
        progress = []
        extracted, filename = extract_partition_image(
            self.manifest, self.temp.name, "aaaa-bbbb",
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(extracted.image_type, "partition")
        self.assertEqual(extracted.source_size_bytes, 4 * 512)
        self.assertTrue(os.path.isfile(os.path.join(self.temp.name, filename)))
        artifact = extracted.artifacts[0]
        with open(os.path.join(self.temp.name, artifact.filename), "rb") as stream:
            self.assertEqual(stream.read(), self.payload[2048 * 512:2052 * 512])
        with open(os.path.join(self.temp.name, filename), encoding="utf-8") as stream:
            self.assertEqual(ImageManifest.from_json(stream.read()), extracted)
        self.assertTrue(progress)
        self.assertEqual(progress[-1], (2048, 2048))

    def test_signs_extracted_manifest_before_atomic_publication(self):
        def sign(path, secret_key, **kwargs):
            with open(path + ".minisig", "wb") as stream:
                stream.write(b"signature")
        with patch("feclora.storage.disk_image_partition.sign_manifest", side_effect=sign) as signer:
            _manifest, filename = extract_partition_image(
                self.manifest, self.temp.name, "aaaa-bbbb",
                minisign_secret_key="/secure/server.minisign.key",
            )
        signer.assert_called_once()
        self.assertTrue(os.path.isfile(os.path.join(self.temp.name, filename + ".minisig")))
        with open(os.path.join(self.temp.name, filename + ".minisig"), "rb") as stream:
            self.assertEqual(stream.read(), b"signature")

    def test_selects_partition_by_name(self):
        extracted, _ = extract_partition_image(
            self.manifest, self.temp.name, "root fs"
        )
        self.assertEqual(extracted.source_size_bytes, 2048)

    def test_rejects_unknown_or_ambiguous_partition_selector(self):
        with self.assertRaisesRegex(DiskImagePartitionError, "selector is invalid"):
            extract_partition_image(self.manifest, self.temp.name, "missing")

    def test_rejects_corrupt_disk_artifact_before_publishing(self):
        with open(os.path.join(self.temp.name, "source.disk.gz"), "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(DiskImagePartitionError):
            extract_partition_image(self.manifest, self.temp.name, "aaaa-bbbb")
        self.assertEqual(
            [name for name in os.listdir(self.temp.name) if ".partition-" in name],
            [],
        )

    def test_rejects_corrupt_partition_table_before_extracting(self):
        with open(os.path.join(self.temp.name, "source.sfdisk"), "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(DiskImagePartitionError, "stored artifact size|SHA-256"):
            extract_partition_image(self.manifest, self.temp.name, "aaaa-bbbb")


if __name__ == "__main__":
    unittest.main()
