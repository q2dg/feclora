import gzip
import hashlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from feclora.storage.disk_restore import DiskRestoreError, restore_disk


class RecordingInput:
    def __init__(self):
        import io
        self.buffer = io.BytesIO()
    def write(self, data):
        return self.buffer.write(data)
    def close(self):
        pass
    def getvalue(self):
        return self.buffer.getvalue()

class FakeProcess:
    def __init__(self):
        self.stdin = RecordingInput()
        self.returncode = 0
        self.terminated = False
    def poll(self):
        return -15 if self.terminated else self.returncode
    def wait(self):
        return self.poll()
    def terminate(self):
        self.terminated = True


class DiskRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = b"fake disk bytes" * 64
        self.stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.temp.name, "disk.raw.gz"), "wb") as stream:
            stream.write(self.stored)
        manifest = {
            "schema_version": 1, "image_id": "test-image", "image_type": "disk",
            "source_size_bytes": len(self.payload), "logical_sector_size": 512,
            "partition_table": "gpt",
            "artifacts": [
                {"filename": "disk.raw.gz", "role": "disk-image", "format": "raw",
                 "compression": "gzip", "size_bytes": len(self.stored),
                 "sha256": hashlib.sha256(self.stored).hexdigest()},
                {"filename": "table.sfdisk", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": 1, "sha256": "a" * 64},
            ],
        }
        self.manifest = os.path.join(self.temp.name, "image.manifest.json")
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
        self.executables = {"dd": "/usr/bin/dd", "lsblk": "/usr/bin/lsblk"}
        self.started = []
    def runner(self, command, **kwargs):
        return SimpleNamespace(stdout=f"{len(self.payload) + 1024} disk\n")
    def restore(self, **kwargs):
        return restore_disk(
            self.manifest, self.temp.name, "/dev/fake",
            confirmation="ERASE /dev/fake", executables=self.executables,
            device_validator=lambda _path: True, runner=self.runner,
            target_safety_check=lambda _path: None,
            popen_factory=lambda *args, **kw: self.started.append((args, kw)) or FakeProcess(),
            **kwargs,
        )
    def test_requires_exact_destructive_confirmation(self):
        with self.assertRaisesRegex(DiskRestoreError, "confirmation"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake", confirmation="yes",
                executables=self.executables, device_validator=lambda _path: True,
                runner=self.runner, target_safety_check=lambda _path: None,
                popen_factory=lambda *a, **k: self.fail("dd must not start"),
            )
    def test_validates_digest_before_starting_dd(self):
        with open(os.path.join(self.temp.name, "disk.raw.gz"), "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(DiskRestoreError, "size|SHA-256"):
            self.restore()
        self.assertEqual(self.started, [])
    def test_rejects_small_target_before_starting_dd(self):
        def small_runner(command, **kwargs):
            return SimpleNamespace(stdout="10 disk\n")
        with self.assertRaisesRegex(DiskRestoreError, "smaller"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake",
                confirmation="ERASE /dev/fake", executables=self.executables,
                device_validator=lambda _path: True, runner=small_runner,
                target_safety_check=lambda _path: None,
                popen_factory=lambda *a, **k: self.fail("dd must not start"),
            )
    def test_streams_verified_decompressed_bytes_to_dd(self):
        proc = FakeProcess()
        result = restore_disk(
            self.manifest, self.temp.name, "/dev/fake",
            confirmation="ERASE /dev/fake", executables=self.executables,
            device_validator=lambda _path: True, runner=self.runner,
            target_safety_check=lambda _path: None,
            popen_factory=lambda *args, **kwargs: proc,
        )
        self.assertEqual(result.image_id, "test-image")
        self.assertEqual(proc.stdin.getvalue(), self.payload)
    def test_rechecks_target_safety_before_dd(self):
        calls = []
        def safety(_path):
            calls.append(True)
            if len(calls) == 2:
                from feclora.storage.source_safety import SourceSafetyError
                raise SourceSafetyError("mounted")
        with self.assertRaisesRegex(DiskRestoreError, "became unsafe"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake",
                confirmation="ERASE /dev/fake", executables=self.executables,
                device_validator=lambda _path: True, runner=self.runner,
                target_safety_check=safety,
                popen_factory=lambda *a, **k: self.fail("dd must not start"),
            )


if __name__ == "__main__":
    unittest.main()
