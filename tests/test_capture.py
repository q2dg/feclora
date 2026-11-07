import io
import os
import tempfile
import unittest

from feclora.storage.capture import (
    CaptureError,
    build_capture_plan,
    capture_partition,
)


class FakeProcess:
    def __init__(self, argv, stdout_data=b"captured partition bytes", returncode=0):
        self.argv = argv
        self.stdout = io.BytesIO(stdout_data)
        self._returncode = returncode
        self.terminated = False

    def poll(self):
        return self._returncode if not self.terminated else -15

    def wait(self):
        return self._returncode if not self.terminated else -15

    def terminate(self):
        self.terminated = True


class CaptureTests(unittest.TestCase):
    def test_partclone_plan_uses_stdout_and_filesystem_aware_format(self):
        plan = build_capture_plan(
            "/dev/sda1", "ext4",
            {"partclone.ext4": "/usr/sbin/partclone.ext4", "dd": "/usr/bin/dd"},
        )
        self.assertEqual(plan.image_format, "partclone")
        self.assertEqual(
            plan.argv,
            ("/usr/sbin/partclone.ext4", "-c", "-s", "/dev/sda1"),
        )

    def test_unknown_filesystem_uses_raw_dd(self):
        plan = build_capture_plan("/dev/sda1", "unknown", {"dd": "/usr/bin/dd"})
        self.assertEqual(plan.image_format, "raw")
        self.assertEqual(
            plan.argv,
            ("/usr/bin/dd", "if=/dev/sda1", "bs=4M", "status=none"),
        )

    def test_no_supported_tool_fails_closed(self):
        with self.assertRaises(CaptureError):
            build_capture_plan("/dev/sda1", "mystery", {"dd": None})

    def test_rejects_non_device_source(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(CaptureError, "block device"):
                capture_partition(
                    "/dev/not-a-device", "ext4", directory, "part.img",
                    "1", {"partclone.extfs": "/usr/bin/partclone.extfs"},
                )

    def test_successful_capture_publishes_only_after_process_success(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = FakeProcess(["/usr/bin/dd"])
            def factory(argv, **kwargs):
                self.assertEqual(argv[0], "/usr/bin/dd")
                return proc
            artifact = capture_partition(
                "/dev/fake1", "unknown", directory, "part.raw", "1",
                {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                source_safety_check=lambda _path: None,
                popen_factory=factory,
            )
            with open(os.path.join(directory, "part.raw"), "rb") as stream:
                self.assertEqual(stream.read(), b"captured partition bytes")
            self.assertEqual(artifact.format, "raw")
            self.assertEqual(
                sorted(os.listdir(directory)), ["part.raw"]
            )

    def test_failed_producer_does_not_publish_partial_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = FakeProcess(["/usr/bin/dd"], returncode=1)
            with self.assertRaisesRegex(CaptureError, "status 1"):
                capture_partition(
                    "/dev/fake1", None, directory, "part.raw", "1",
                    {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None,
                    popen_factory=lambda *_args, **_kwargs: proc,
                )
            self.assertEqual(os.listdir(directory), [])

    def test_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "part.raw")
            with open(path, "wb") as stream:
                stream.write(b"keep")
            proc = FakeProcess(["/usr/bin/dd"])
            with self.assertRaisesRegex(CaptureError, "already exists"):
                capture_partition(
                    "/dev/fake1", None, directory, "part.raw", "1",
                    {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None,
                    popen_factory=lambda *_args, **_kwargs: proc,
                )
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), b"keep")

    def test_rejects_repository_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            link = directory + "-link"
            os.symlink(directory, link)
            self.addCleanup(os.unlink, link)
            with self.assertRaisesRegex(CaptureError, "not a symlink"):
                capture_partition(
                    "/dev/fake1", None, link, "part.raw", "1",
                    {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                    popen_factory=lambda *_args, **_kwargs: FakeProcess(["dd"]),
                )


if __name__ == "__main__":
    unittest.main()
