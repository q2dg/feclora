import gzip
import hashlib
import io
import lzma
import os
import tempfile
import unittest

from feclora.storage.artifact_writer import ArtifactWriteError, write_artifact


class ArtifactWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = (b"feclora-image-data-" * 1000) + b"end"

    def test_writes_raw_stream_and_records_stored_digest(self):
        artifact = write_artifact(
            self.temp.name, "disk.raw", io.BytesIO(self.payload),
            role="disk-image", image_format="raw",
        )
        path = os.path.join(self.temp.name, "disk.raw")
        with open(path, "rb") as stream:
            stored = stream.read()
        self.assertEqual(stored, self.payload)
        self.assertEqual(artifact.size_bytes, len(stored))
        self.assertEqual(artifact.sha256, hashlib.sha256(stored).hexdigest())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_compresses_gzip_and_xz(self):
        for compression, decoder, suffix in (
            ("gzip", gzip.decompress, ".gz"),
            ("xz", lzma.decompress, ".xz"),
        ):
            with self.subTest(compression=compression):
                name = "image" + suffix
                artifact = write_artifact(
                    self.temp.name, name, io.BytesIO(self.payload),
                    role="partition-image", image_format="partclone",
                    compression=compression, partition_id="1", filesystem="ext4",
                )
                with open(os.path.join(self.temp.name, name), "rb") as stream:
                    stored = stream.read()
                self.assertEqual(decoder(stored), self.payload)
                self.assertEqual(artifact.sha256, hashlib.sha256(stored).hexdigest())

    def test_records_selected_compression_level(self):
        artifact = write_artifact(
            self.temp.name, "image.gz", io.BytesIO(self.payload),
            role="disk-image", image_format="raw", compression="gzip",
            compression_level=1,
        )
        self.assertEqual(artifact.compression_level, 1)
        with open(os.path.join(self.temp.name, "image.gz"), "rb") as stream:
            self.assertEqual(gzip.decompress(stream.read()), self.payload)

    def test_rejects_compression_level_for_uncompressed_artifact(self):
        with self.assertRaisesRegex(ArtifactWriteError, "not valid"):
            write_artifact(
                self.temp.name, "image.raw", io.BytesIO(self.payload),
                role="disk-image", image_format="raw", compression_level=3,
            )

    def test_refuses_to_overwrite_existing_file(self):
        path = os.path.join(self.temp.name, "existing.img")
        with open(path, "wb") as stream:
            stream.write(b"keep")
        with self.assertRaisesRegex(ArtifactWriteError, "already exists"):
            write_artifact(self.temp.name, "existing.img", io.BytesIO(self.payload),
                           role="disk-image", image_format="raw")
        with open(path, "rb") as stream:
            self.assertEqual(stream.read(), b"keep")

    def test_rejects_unsafe_names_symlink_directory_and_unsupported_compression(self):
        with self.assertRaises(ArtifactWriteError):
            write_artifact(self.temp.name, "../escape", io.BytesIO(self.payload),
                           role="disk-image", image_format="raw")
        with self.assertRaises(ArtifactWriteError):
            write_artifact(self.temp.name, "image.zst", io.BytesIO(self.payload),
                           role="disk-image", image_format="raw", compression="zstd")
        link = self.temp.name + "-link"
        os.symlink(self.temp.name, link)
        self.addCleanup(os.unlink, link)
        with self.assertRaises(ArtifactWriteError):
            write_artifact(link, "image.raw", io.BytesIO(self.payload),
                           role="disk-image", image_format="raw")

    def test_rejects_empty_input_and_removes_temporary_file(self):
        with self.assertRaisesRegex(ArtifactWriteError, "empty"):
            write_artifact(self.temp.name, "empty.img", io.BytesIO(b""),
                           role="disk-image", image_format="raw")
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_cleans_up_after_source_failure(self):
        class BrokenStream:
            def __init__(self):
                self.calls = 0
            def read(self, size):
                self.calls += 1
                if self.calls == 1:
                    return b"partial"
                raise OSError("simulated read failure")

        with self.assertRaises(ArtifactWriteError):
            write_artifact(self.temp.name, "broken.img", BrokenStream(),
                           role="disk-image", image_format="raw")
        self.assertEqual(os.listdir(self.temp.name), [])


if __name__ == "__main__":
    unittest.main()
