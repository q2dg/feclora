import io
import os
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.disk_capture import DiskCaptureError, capture_disk
from feclora.storage.capture import CaptureCancelled


class FakeProcess:
    def __init__(self, data=b"whole disk bytes", returncode=0):
        self.stdout = io.BytesIO(data)
        self.returncode = returncode
        self.terminated = False
    def poll(self):
        return -15 if self.terminated else self.returncode
    def wait(self):
        return self.poll()
    def terminate(self):
        self.terminated = True


class DiskCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.disk_size = len(b"whole disk bytes")
        self.executables = {
            "dd": "/usr/bin/dd", "sfdisk": "/usr/sbin/sfdisk",
            "lsblk": "/usr/bin/lsblk",
        }

    def runner(self, command, **kwargs):
        if command[0] == self.executables["lsblk"]:
            return SimpleNamespace(stdout=f"{self.disk_size} 512 gpt\n")
        if command[0] == self.executables["sfdisk"]:
            return SimpleNamespace(stdout="label: gpt\n")
        raise AssertionError(command)

    def test_captures_disk_and_publishes_manifest_last(self):
        proc = FakeProcess(b"raw disk payload")
        manifest = capture_disk(
            "/dev/fake", "backup-01", self.temp.name,
            executables=self.executables,
            device_validator=lambda _path: True,
            runner=self.runner,
            source_safety_check=lambda _path: None, effective_uid=lambda: 0,
            popen_factory=lambda *_args, **_kwargs: proc,
        )
        self.assertEqual(manifest.image_type, "disk")
        self.assertEqual(manifest.partition_table, "gpt")
        self.assertEqual(
            set(os.listdir(self.temp.name)),
            {"backup-01.disk.raw", "backup-01.sfdisk", "backup-01.manifest.json"},
        )
        self.assertEqual(len(manifest.artifacts), 2)

    def test_reports_raw_read_progress(self):
        payload = b"whole disk bytes"
        progress = []
        capture_disk(
            "/dev/fake", "progress-image", self.temp.name,
            executables=self.executables, device_validator=lambda _path: True,
            runner=self.runner, source_safety_check=lambda _path: None,
            effective_uid=lambda: 0,
            popen_factory=lambda *_args, **_kwargs: FakeProcess(payload),
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(progress[-1], (len(payload), len(payload)))
    def test_cancellation_does_not_publish_payload_or_manifest(self):
        proc = FakeProcess(b"partial payload")
        def cancel(_done, _total):
            raise CaptureCancelled("operator cancelled")
        with self.assertRaisesRegex(CaptureCancelled, "cancelled"):
            capture_disk(
                "/dev/fake", "cancelled-image", self.temp.name,
                executables=self.executables, device_validator=lambda _path: True,
                runner=self.runner, source_safety_check=lambda _path: None,
                effective_uid=lambda: 0,
                popen_factory=lambda *_args, **_kwargs: proc,
                progress_callback=cancel,
            )
        self.assertEqual(os.listdir(self.temp.name), [])
        self.assertTrue(proc.terminated)
    def test_failed_dd_leaves_no_published_files(self):
        proc = FakeProcess(b"partial", returncode=1)
        with self.assertRaisesRegex(DiskCaptureError, "status 1"):
            capture_disk(
                "/dev/fake", "bad-image", self.temp.name,
                executables=self.executables,
                device_validator=lambda _path: True,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                runner=self.runner,
                popen_factory=lambda *_args, **_kwargs: proc,
            )
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_existing_name_aborts_without_overwrite(self):
        with open(os.path.join(self.temp.name, "taken.disk.raw"), "wb") as stream:
            stream.write(b"preserve")
        with self.assertRaisesRegex(DiskCaptureError, "already exists"):
            capture_disk(
                "/dev/fake", "taken", self.temp.name,
                executables=self.executables,
                device_validator=lambda _path: True,
                runner=self.runner,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
            )
        with open(os.path.join(self.temp.name, "taken.disk.raw"), "rb") as stream:
            self.assertEqual(stream.read(), b"preserve")
        self.assertEqual(os.listdir(self.temp.name), ["taken.disk.raw"])

    def test_short_read_does_not_publish_a_disk_manifest(self):
        with self.assertRaisesRegex(DiskCaptureError, "size mismatch"):
            capture_disk(
                "/dev/fake", "short-image", self.temp.name,
                executables=self.executables, device_validator=lambda _path: True,
                runner=self.runner, source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *_args, **_kwargs: FakeProcess(b"short"),
            )
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_invalid_geometry_fails_before_capture(self):
        def bad_runner(command, **kwargs):
            return SimpleNamespace(stdout="bad geometry\n")
        with self.assertRaisesRegex(DiskCaptureError, "invalid disk geometry"):
            capture_disk(
                "/dev/fake", "bad", self.temp.name,
                executables=self.executables,
                device_validator=lambda _path: True,
                runner=bad_runner,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *_args, **_kwargs: self.fail("dd must not start"),
            )
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_manifest_collision_rolls_back_new_payload_artifacts(self):
        with open(os.path.join(self.temp.name, "manifest-taken.manifest.json"), "w") as stream:
            stream.write("existing manifest")
        with self.assertRaisesRegex(DiskCaptureError, "already exists"):
            capture_disk(
                "/dev/fake", "manifest-taken", self.temp.name,
                executables=self.executables,
                device_validator=lambda _path: True,
                runner=self.runner,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *_args, **_kwargs: FakeProcess(),
            )
        self.assertEqual(os.listdir(self.temp.name), ["manifest-taken.manifest.json"])


if __name__ == "__main__":
    unittest.main()
