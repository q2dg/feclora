import gzip
import hashlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from feclora.storage.disk_restore import DiskRestoreCancelled, DiskRestoreError, restore_disk


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
    def __init__(self, readback=b""):
        self.stdin = RecordingInput()
        self.stdout = io.BytesIO(readback)
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
        return SimpleNamespace(stdout=f"{len(self.payload) + 1024} disk 512 0\n")
    def restore(self, **kwargs):
        return restore_disk(
            self.manifest, self.temp.name, "/dev/fake",
            confirmation="ERASE /dev/fake", executables=self.executables,
            device_validator=lambda _path: True, runner=self.runner,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=lambda *args, **kw: self.started.append((args, kw)) or FakeProcess(self.payload),
            **kwargs,
        )
    def test_requires_exact_destructive_confirmation(self):
        with self.assertRaisesRegex(DiskRestoreError, "confirmation"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake", confirmation="yes",
                executables=self.executables, device_validator=lambda _path: True,
                runner=self.runner, target_safety_check=lambda _path: None, effective_uid=lambda: 0,
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
            return SimpleNamespace(stdout="10 disk 512 0\n")
        with self.assertRaisesRegex(DiskRestoreError, "smaller"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake",
                confirmation="ERASE /dev/fake", executables=self.executables,
                device_validator=lambda _path: True, runner=small_runner,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: self.fail("dd must not start"),
            )
    def test_age_encrypted_restore_requires_identity_before_dd(self):
        with open(self.manifest, encoding="utf-8") as stream:
            manifest = json.load(stream)
        manifest["artifacts"][0]["encryption"] = "age"
        with open(self.manifest, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream)
        with self.assertRaisesRegex(DiskRestoreError, "identity file is required"):
            self.restore()
        self.assertEqual(self.started, [])

    def test_can_require_minisign_signature_before_dd(self):
        with self.assertRaisesRegex(DiskRestoreError, "signature is required"):
            self.restore(require_signature=True)
        self.assertEqual(self.started, [])

    def test_pre_write_callback_runs_after_successful_preflight(self):
        calls = []
        self.restore(pre_write_callback=lambda: calls.append("authorized"))
        self.assertEqual(calls, ["authorized"])
        self.assertEqual(len(self.started), 2)

    def test_pre_write_callback_does_not_run_when_artifact_preflight_fails(self):
        with open(os.path.join(self.temp.name, "disk.raw.gz"), "ab") as stream:
            stream.write(b"tamper")
        calls = []
        with self.assertRaises(DiskRestoreError):
            self.restore(pre_write_callback=lambda: calls.append("authorized"))
        self.assertEqual(calls, [])
        self.assertEqual(self.started, [])

    def test_streams_verified_decompressed_bytes_to_dd(self):
        proc = FakeProcess(self.payload)
        result = restore_disk(
            self.manifest, self.temp.name, "/dev/fake",
            confirmation="ERASE /dev/fake", executables=self.executables,
            device_validator=lambda _path: True, runner=self.runner,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=lambda *args, **kwargs: proc,
        )
        self.assertEqual(result.image_id, "test-image")
        self.assertEqual(proc.stdin.getvalue(), self.payload)
    def test_reports_restore_write_progress(self):
        progress = []
        proc = FakeProcess(self.payload)
        result = restore_disk(
            self.manifest, self.temp.name, "/dev/fake",
            confirmation="ERASE /dev/fake", executables=self.executables,
            device_validator=lambda _path: True, runner=self.runner,
            target_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=lambda *a, **k: proc,
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(result.image_id, "test-image")
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
    def test_cancellation_stops_dd_and_reports_partial_target(self):
        class RunningProcess(FakeProcess):
            def poll(self):
                return -15 if self.terminated else None
        proc = RunningProcess()
        with self.assertRaisesRegex(DiskRestoreCancelled, "cancel"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake",
                confirmation="ERASE /dev/fake", executables=self.executables,
                device_validator=lambda _path: True, runner=self.runner,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: proc,
                progress_callback=lambda *_args: (_ for _ in ()).throw(DiskRestoreCancelled("operator cancel")),
            )
        self.assertTrue(proc.terminated)
    def test_rejects_destination_readback_mismatch(self):
        processes = []
        def factory(*args, **kwargs):
            proc = FakeProcess(self.payload if not processes else b"corrupted target")
            processes.append(proc)
            return proc
        with self.assertRaisesRegex(DiskRestoreError, "read-back verification failed"):
            restore_disk(
                self.manifest, self.temp.name, "/dev/fake",
                confirmation="ERASE /dev/fake", executables=self.executables,
                device_validator=lambda _path: True, runner=self.runner,
                target_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
            )
        self.assertEqual(len(processes), 2)
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
                target_safety_check=safety, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: self.fail("dd must not start"),
            )


if __name__ == "__main__":
    unittest.main()
