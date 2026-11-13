import gzip
import hashlib
import io
import lzma
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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

    @unittest.skipUnless(shutil.which("zstd") and shutil.which("lz4"), "zstd and lz4 executables are required")
    def test_compresses_zstd_and_lz4_with_selected_levels(self):
        for codec, level, suffix in (("zstd", 7, ".zst"), ("lz4", 5, ".lz4")):
            with self.subTest(codec=codec):
                filename = "image" + suffix
                artifact = write_artifact(
                    self.temp.name, filename, io.BytesIO(self.payload),
                    role="disk-image", image_format="raw",
                    compression=codec, compression_level=level,
                )
                with open(os.path.join(self.temp.name, filename), "rb") as stored:
                    encoded = stored.read()
                decoded = subprocess.run(
                    [codec, "-q", "-d", "-c"], input=encoded,
                    check=True, capture_output=True,
                ).stdout
                self.assertEqual(decoded, self.payload)
                self.assertEqual(artifact.compression_level, level)
                self.assertEqual(artifact.size_bytes, len(encoded))
                self.assertEqual(artifact.sha256, hashlib.sha256(encoded).hexdigest())

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
                           role="disk-image", image_format="raw", compression="zstd",
                           compression_executable="/definitely/missing/zstd")
        link = self.temp.name + "-link"
        os.symlink(self.temp.name, link)
        self.addCleanup(os.unlink, link)
        with self.assertRaises(ArtifactWriteError):
            write_artifact(link, "image.raw", io.BytesIO(self.payload),
                           role="disk-image", image_format="raw")

    def test_rolls_back_final_link_if_staging_unlink_fails(self):
        real_unlink = os.unlink
        failed = False

        def fail_staging_unlink(path, *args, **kwargs):
            nonlocal failed
            if isinstance(path, str) and path.endswith(".tmp") and not failed:
                failed = True
                raise OSError("simulated staging unlink failure")
            return real_unlink(path, *args, **kwargs)

        with patch("feclora.storage.artifact_writer.os.unlink", side_effect=fail_staging_unlink):
            with self.assertRaises(ArtifactWriteError):
                write_artifact(
                    self.temp.name, "interrupted.img", io.BytesIO(self.payload),
                    role="disk-image", image_format="raw",
                )

        self.assertFalse(os.path.lexists(os.path.join(self.temp.name, "interrupted.img")))
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_rollback_preserves_concurrent_replacement_of_final_name(self):
        real_unlink = os.unlink
        replaced = False
        final_name = "raced.img"

        def replace_final_before_staging_unlink(path, *args, **kwargs):
            nonlocal replaced
            if path.startswith(".feclora-") and path.endswith(".tmp") and not replaced:
                replaced = True
                dir_fd = kwargs.get("dir_fd")
                real_unlink(final_name, dir_fd=dir_fd)
                replacement_fd = os.open(
                    final_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                    dir_fd=dir_fd,
                )
                with os.fdopen(replacement_fd, "wb") as stream:
                    stream.write(b"concurrent replacement")
                raise OSError("simulated staging unlink failure")
            return real_unlink(path, *args, **kwargs)

        with patch("feclora.storage.artifact_writer.os.unlink", side_effect=replace_final_before_staging_unlink):
            with self.assertRaises(ArtifactWriteError):
                write_artifact(
                    self.temp.name, final_name, io.BytesIO(self.payload),
                    role="disk-image", image_format="raw",
                )

        with open(os.path.join(self.temp.name, final_name), "rb") as stream:
            self.assertEqual(stream.read(), b"concurrent replacement")
        self.assertEqual(os.listdir(self.temp.name), [final_name])

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
