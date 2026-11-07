import unittest

from feclora.storage.image_manifest import ImageManifest, ManifestValidationError


def artifact(**changes):
    value = {
        "filename": "partition-1.img.zst",
        "role": "partition-image",
        "format": "partclone",
        "compression": "zstd",
        "size_bytes": 4096,
        "sha256": "a" * 64,
        "partition_id": "1",
    }
    value.update(changes)
    return value


def disk_manifest(**changes):
    value = {
        "schema_version": 1,
        "image_id": "golden-image",
        "image_type": "disk",
        "source_size_bytes": 1000000,
        "logical_sector_size": 512,
        "partition_table": "gpt",
        "artifacts": [
            artifact(filename="partition-1.img.zst"),
            artifact(
                filename="partition-table.sfdisk",
                role="partition-table",
                format="raw",
                compression="none",
                partition_id=None,
            ),
        ],
    }
    value.update(changes)
    return value


class ImageManifestTests(unittest.TestCase):
    def test_validates_and_round_trips_disk_manifest(self):
        manifest = ImageManifest.from_dict(disk_manifest())
        decoded = ImageManifest.from_json(manifest.to_json())
        self.assertEqual(decoded, manifest)
        self.assertEqual(decoded.image_type, "disk")

    def test_rejects_path_traversal_artifact_names(self):
        for filename in ("../disk.img", "/tmp/disk.img", "subdir/file.img", ".."):
            with self.subTest(filename=filename):
                with self.assertRaises(ManifestValidationError):
                    ImageManifest.from_dict(disk_manifest(artifacts=[
                        artifact(filename=filename),
                        artifact(
                            filename="partition-table.sfdisk",
                            role="partition-table",
                            format="raw",
                            compression="none",
                            partition_id=None,
                        ),
                    ]))

    def test_rejects_duplicate_artifact_names(self):
        with self.assertRaisesRegex(ManifestValidationError, "unique"):
            ImageManifest.from_dict(disk_manifest(artifacts=[
                artifact(),
                artifact(role="partition-table", format="raw", compression="none", partition_id=None),
            ]))

    def test_rejects_invalid_hash_and_size(self):
        with self.assertRaisesRegex(ManifestValidationError, "sha256"):
            ImageManifest.from_dict(disk_manifest(artifacts=[
                artifact(sha256="not-a-hash"),
                artifact(
                    filename="partition-table.sfdisk",
                    role="partition-table",
                    format="raw",
                    compression="none",
                    partition_id=None,
                ),
            ]))
        with self.assertRaisesRegex(ManifestValidationError, "positive integer"):
            ImageManifest.from_dict(disk_manifest(source_size_bytes=True))

    def test_disk_image_requires_partition_table(self):
        with self.assertRaisesRegex(ManifestValidationError, "partition-table"):
            ImageManifest.from_dict(disk_manifest(artifacts=[artifact()]))

    def test_partition_image_cannot_include_disk_table(self):
        with self.assertRaisesRegex(ManifestValidationError, "Partition image"):
            ImageManifest.from_dict(disk_manifest(
                image_type="partition",
                partition_table="none",
                artifacts=[
                    artifact(
                        role="partition-table",
                        format="raw",
                        compression="none",
                        partition_id=None,
                    )
                ],
            ))

    def test_partition_manifest(self):
        manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": "root-partition",
            "image_type": "partition",
            "source_size_bytes": 500000,
            "logical_sector_size": 512,
            "partition_table": "none",
            "artifacts": [artifact()],
        })
        self.assertEqual(manifest.artifacts[0].partition_id, "1")

    def test_rejects_unknown_fields_and_invalid_schema(self):
        with self.assertRaisesRegex(ManifestValidationError, "Unknown"):
            ImageManifest.from_dict(disk_manifest(untrusted_command="dd"))
        with self.assertRaisesRegex(ManifestValidationError, "schema_version"):
            ImageManifest.from_dict(disk_manifest(schema_version=True))


if __name__ == "__main__":
    unittest.main()
