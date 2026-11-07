import gzip
import hashlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from feclora.storage.partition_restore import PartitionRestoreError, restore_partition


class FakeProcess:
    def __init__(self):
        self.returncode = 0
        self.stdin = None
        self.argv = None
    def wait(self):
        return self.returncode
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15


class PartitionRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = b"raw partition payload" * 20
        self.stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.temp.name, "partition.img.gz"), "wb") as stream:
            stream.write(self.stored)
        self.manifest = os.path.join(self.temp.name, "part.manifest.json")
        self.write_manifest("raw", None, len(self.payload))
        self.calls = []
    def write_manifest(self, image_format, filesystem, size):
        artifact = {
            "filename": "partition.img.gz", "role": "partition-image",
            "format": image_format, "compression": "gzip",
            "size_bytes": len(self.stored), "sha256": hashlib.sha256(self.stored).hexdigest(),
            "partition_id": "sda1",
        }
        if filesystem:
            artifact["filesystem"] = filesystem
        manifest = {
            "schema_version": 1, "image_id": "partition-test", "image_type": "partition",
            "source_size_bytes": size, "logical_sector_size": 512,
            "partition_table": "none", "artifacts": [artifact],
        }
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
    def runner(self, command, **kwargs):
        return SimpleNamespace(stdout=f"{len(self.payload) + 1024} part\n")
    def restore(self, **kwargs):
        proc = FakeProcess()
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        result = restore_partition(
            self.manifest, self.temp.name, "/dev/sda1",
            confirmation="ERASE /dev/sda1",
            executables={"lsblk": "lsblk", "dd": "dd", "partclone.ext4": "partclone.ext4"},
            runner=self.runner, target_safety_check=lambda _path: None,
            popen_factory=factory, **kwargs,
        )
        return result
    def test_raw_restore_uses_dd_and_verified_decompressed_file(self):
        self.restore()
        argv, options = self.calls[0]
        self.assertEqual(argv[0], "dd")
        self.assertEqual(options["stdin"].read(), self.payload)
    def test_partclone_restore_uses_filesystem_specific_executable(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        self.restore()
        argv, options = self.calls[0]
        self.assertEqual(argv[0], "partclone.ext4")
        self.assertEqual(argv[1:3], ["-r", "-s"])
        self.assertIn("pass_fds", options)
    def test_requires_exact_confirmation(self):
        with self.assertRaisesRegex(PartitionRestoreError, "confirmation"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1", confirmation="yes",
                executables={"lsblk": "lsblk"}, runner=self.runner,
                target_safety_check=lambda _path: None,
            )
    def test_rejects_corrupt_artifact_before_starting_writer(self):
        with open(os.path.join(self.temp.name, "partition.img.gz"), "ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(PartitionRestoreError, "SHA-256"):
            self.restore()
        self.assertEqual(self.calls, [])
    def test_rejects_too_small_target(self):
        def small(command, **kwargs):
            return SimpleNamespace(stdout="1 part\n")
        with self.assertRaisesRegex(PartitionRestoreError, "smaller"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1", executables={"lsblk": "lsblk", "dd": "dd"},
                runner=small, target_safety_check=lambda _path: None,
                popen_factory=lambda *a, **k: self.fail("writer must not start"),
            )


if __name__ == "__main__":
    unittest.main()
