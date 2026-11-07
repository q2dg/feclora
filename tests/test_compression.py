import shutil
import subprocess
import unittest
import tempfile

from feclora.storage.compression import ExternalDecompressionStream


@unittest.skipUnless(shutil.which("zstd") and shutil.which("lz4"), "zstd and lz4 executables are required")
class ExternalCodecTests(unittest.TestCase):
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
