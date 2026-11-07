import gzip
import hashlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from feclora.storage.partition_restore import PartitionRestoreCancelled, PartitionRestoreError, restore_partition


class RecordingInput:
    def __init__(self):
        self.buffer = io.BytesIO()
    def write(self, data):
        return self.buffer.write(data)
    def close(self):
        pass
    def getvalue(self):
        return self.buffer.getvalue()


class FakeProcess:
    def __init__(self):
        self.returncode = 0
        self.stdin = RecordingInput()
        self.stderr = io.BytesIO(b"Progress: 25.0%\\rProgress: 75.0%\\r")
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
        self.stdin_data = None
        self.partclone_data = None
        self.active_process = None
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
        return SimpleNamespace(stdout=f"{len(self.payload) + 1024} part 512 0\n")
    def restore(self, **kwargs):
        proc = FakeProcess()
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            if argv[0] == "dd":
                self.active_process = proc
            elif argv[0].startswith("partclone."):
                with open(argv[3], "rb") as image:
                    self.partclone_data = image.read()
            return proc
        result = restore_partition(
            self.manifest, self.temp.name, "/dev/sda1",
            confirmation="ERASE /dev/sda1",
            executables={"lsblk": "lsblk", "dd": "dd", "partclone.ext4": "partclone.ext4"},
            runner=self.runner, device_validator=lambda _path: True,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=factory, **kwargs,
        )
        if self.active_process is not None:
            self.stdin_data = self.active_process.stdin.getvalue()
        return result
    def test_age_encrypted_restore_requires_identity_before_writer(self):
        with open(self.manifest, encoding="utf-8") as stream:
            manifest = json.load(stream)
        manifest["artifacts"][0]["encryption"] = "age"
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
        with self.assertRaisesRegex(PartitionRestoreError, "identity file is required"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_can_require_minisign_signature_before_writer(self):
        with self.assertRaisesRegex(PartitionRestoreError, "signature is required"):
            self.restore(require_signature=True)
        self.assertEqual(self.calls, [])

    def test_raw_restore_uses_dd_and_verified_decompressed_file(self):
        self.restore()
        argv, options = self.calls[0]
        self.assertEqual(argv[0], "dd")
        self.assertEqual(self.stdin_data, self.payload)
    def test_raw_restore_reports_progress(self):
        progress = []
        self.restore(progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
    def test_raw_restore_cancellation_stops_writer(self):
        proc = FakeProcess()
        class RunningProcess(FakeProcess):
            def poll(self):
                return -15 if self.returncode == -15 else None
        proc = RunningProcess()
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        with self.assertRaisesRegex(PartitionRestoreCancelled, "cancel"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "dd": "dd"},
                runner=self.runner, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
                progress_callback=lambda *_args: (_ for _ in ()).throw(PartitionRestoreCancelled("operator cancel")),
            )
        self.assertEqual(proc.returncode, -15)
    def test_partclone_restore_uses_filesystem_specific_executable(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        self.restore()
        argv, options = self.calls[0]
        self.assertEqual(argv[0], "partclone.ext4")
        self.assertEqual(argv[1:3], ["-r", "-s"])
        self.assertEqual(self.partclone_data, self.payload)
        self.assertNotIn("pass_fds", options)

    def test_partclone_restore_reports_progress_from_stderr(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        progress = []
        self.restore(progress_callback=lambda done, total: progress.append((done, total)))
        self.assertIn((25, 100), progress)
        self.assertIn((75, 100), progress)
        self.assertIn("-F", self.calls[0][0])
        self.assertIn("1", self.calls[0][0])

    def test_partclone_restore_cancellation_terminates_writer(self):
        self.write_manifest("partclone", "ext4", len(self.payload))
        class RunningProcess(FakeProcess):
            def poll(self):
                return -15 if self.returncode == -15 else None
        proc = RunningProcess()
        proc.stderr = io.BytesIO(b"Progress: 10%\\r")
        def factory(argv, **opts):
            self.calls.append((argv, opts))
            return proc
        with self.assertRaisesRegex(PartitionRestoreCancelled, "cancel"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1",
                executables={"lsblk": "lsblk", "partclone.ext4": "partclone.ext4"},
                runner=self.runner, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
                progress_callback=lambda *_args: (_ for _ in ()).throw(PartitionRestoreCancelled("operator cancel")),
            )
        self.assertEqual(proc.returncode, -15)
    def test_requires_exact_confirmation(self):
        with self.assertRaisesRegex(PartitionRestoreError, "confirmation"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1", confirmation="yes",
                executables={"lsblk": "lsblk"}, runner=self.runner,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            )
    def test_rejects_corrupt_artifact_before_starting_writer(self):
        with open(os.path.join(self.temp.name, "partition.img.gz"), "ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(PartitionRestoreError, "SHA-256"):
            self.restore()
        self.assertEqual(self.calls, [])
    def test_rejects_too_small_target(self):
        def small(command, **kwargs):
            return SimpleNamespace(stdout="1 part 512 0\n")
        with self.assertRaisesRegex(PartitionRestoreError, "smaller"):
            restore_partition(
                self.manifest, self.temp.name, "/dev/sda1",
                confirmation="ERASE /dev/sda1", executables={"lsblk": "lsblk", "dd": "dd"},
                runner=small, device_validator=lambda _path: True,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: self.fail("writer must not start"),
            )


if __name__ == "__main__":
    unittest.main()
