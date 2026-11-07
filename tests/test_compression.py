import shutil
import subprocess
import unittest
import tempfile
import os
from types import SimpleNamespace

from feclora.storage.compression import CompressionError, ExternalDecompressionStream
from feclora.storage.disk_restore import _preflight_decoded_size
from feclora.storage.partition_restore import _decompress_to_temp


@unittest.skipUnless(shutil.which("zstd") and shutil.which("lz4"), "zstd and lz4 executables are required")
class ExternalCodecTests(unittest.TestCase):
    def test_restore_preflight_and_partition_staging_accept_both_codecs(self):
        payload = b"feclora restore pipeline" * 2048
        for codec, level in (("zstd", 4), ("lz4", 6)):
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as directory:
                encoded = subprocess.run(
                    [codec, "-q", "-c", f"-{level}"],
                    input=payload, check=True, capture_output=True,
                ).stdout
                with tempfile.TemporaryFile(mode="w+b") as source:
                    source.write(encoded)
                    source.seek(0)
                    _preflight_decoded_size(source, SimpleNamespace(compression=codec), len(payload), {codec: shutil.which(codec)})
                    self.assertEqual(source.tell(), 0)
                    staged, size = _decompress_to_temp(source, codec, len(payload), directory, {codec: shutil.which(codec)})
                try:
                    self.assertEqual(size, len(payload))
                    with open(staged, "rb") as restored:
                        self.assertEqual(restored.read(), payload)
                finally:
                    os.unlink(staged)

    def test_external_decompressor_reports_corrupt_input(self):
        for codec in ("zstd", "lz4"):
            with self.subTest(codec=codec), tempfile.TemporaryFile(mode="w+b") as source:
                source.write(b"not a valid compressed stream")
                source.seek(0)
                decoder = ExternalDecompressionStream(source, codec)
                while decoder.read(4096):
                    pass
                with self.assertRaises(CompressionError):
                    decoder.finish()
                decoder.close()

    def test_decompressors_stream_to_eof_and_check_exit_status(self):
        payload = b"feclora codec integration payload" * 2048
        for codec, level in (("zstd", 4), ("lz4", 6)):
            with self.subTest(codec=codec):
                encoded = subprocess.run(
                    [codec, "-q", "-c", f"-{level}"],
                    input=payload, check=True, capture_output=True,
                ).stdout
                with tempfile.TemporaryFile(mode="w+b") as source:
                    source.write(encoded)
                    source.seek(0)
                    decoder = ExternalDecompressionStream(source, codec)
                    chunks = []
                    while True:
                        chunk = decoder.read(8192)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    decoder.finish()
                    decoder.close()
                    self.assertEqual(b"".join(chunks), payload)


if __name__ == "__main__":
    unittest.main()
