import io
import os
import tempfile
import unittest
from unittest.mock import patch

from feclora.storage.capture import (
    CaptureCancelled,
    CaptureError,
    build_capture_plan,
    capture_partition,
    _read_partclone_status,
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
            ("/usr/sbin/partclone.ext4", "-c", "-s", "/dev/sda1", "-F", "-f", "1"),
        )

    def test_supported_filesystems_select_expected_partclone_tools(self):
        from feclora.storage.capture import _FILESYSTEM_TO_PARTCLONE
        expected = {
            "ext2": "partclone.extfs", "ext3": "partclone.extfs",
            "ext4": "partclone.ext4", "xfs": "partclone.xfs",
            "btrfs": "partclone.btrfs", "f2fs": "partclone.f2fs",
            "ntfs": "partclone.ntfs", "ntfs3": "partclone.ntfs",
            "fat": "partclone.fat", "fat12": "partclone.fat",
            "fat16": "partclone.fat", "fat32": "partclone.fat",
            "vfat": "partclone.fat", "exfat": "partclone.exfat",
        }
        for filesystem, executable in expected.items():
            with self.subTest(filesystem=filesystem):
                plan = build_capture_plan(
                    "/dev/sda1", filesystem,
                    {executable: "/usr/sbin/" + executable, "dd": "/usr/bin/dd"},
                )
                self.assertEqual(plan.image_format, "partclone")
                self.assertEqual(plan.executable, "/usr/sbin/" + executable)
                self.assertEqual(plan.filesystem, filesystem)
        self.assertTrue(set(expected).issubset(_FILESYSTEM_TO_PARTCLONE))

    def test_partclone_legacy_block_counters_map_to_partition_bytes(self):
        from feclora.storage.capture import _partclone_stderr_progress
        self.assertEqual(
            _partclone_stderr_progress(
                b"Current block: 25, Total block: 100, Complete: 25.00%", 8192,
            ),
            (2048, 8192),
        )
        self.assertIsNone(_partclone_stderr_progress(b"no progress yet", 8192))

    def test_capture_uses_partclone_legacy_stderr_block_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = []
            proc = FakeProcess(["partclone.ext4"], b"partclone stream")
            def factory(argv, **kwargs):
                self.assertIn("-F", argv)
                self.assertIn("-f", argv)
                out_r, out_w = os.pipe()
                err_r, err_w = os.pipe()
                os.write(out_w, b"partclone stream")
                os.close(out_w)
                os.write(err_w, b"Current block: 25, Total block: 100, Complete: 25.00%\r")
                os.close(err_w)
                proc.stdout = os.fdopen(out_r, "rb")
                proc.stderr = os.fdopen(err_r, "rb")
                return proc
            with patch("feclora.storage.capture._partclone_supports_json_status", return_value=False):
                capture_partition(
                    "/dev/fake1", "ext4", directory, "part.img", "1",
                    {"partclone.ext4": "/usr/bin/partclone.ext4"},
                    device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                    expected_size_bytes=8192,
                    progress_callback=lambda done, total: progress.append((done, total)),
                    popen_factory=factory,
                )
            self.assertIn((2048, 8192), progress)
            self.assertEqual(os.listdir(directory), ["part.img"])

    def test_partclone_json_status_is_parsed_as_logical_data_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "status.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    '{"schema_version":1,"partclone":{"block_size":4096,'
                    '"progress":{"copied_blocks":12,"total_block":30}}}'
                )
            self.assertEqual(_read_partclone_status(path), (49152, 122880))

    def test_partclone_json_status_rejects_unsafe_or_invalid_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "status.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write('{"schema_version":1,"partclone":{"progress":{}}}')
            self.assertIsNone(_read_partclone_status(path))
            os.unlink(path)
            os.symlink("/etc/passwd", path)
            self.assertIsNone(_read_partclone_status(path))

    @patch("feclora.storage.capture._partclone_supports_json_status", return_value=True)
    def test_capture_uses_native_partclone_status_when_supported(self, supports_json):
        with tempfile.TemporaryDirectory() as directory:
            progress = []
            payload = b"partclone stream"
            def factory(argv, **kwargs):
                status_arg = next(arg for arg in argv if arg.startswith("--json-status="))
                status_path = status_arg.split("=", 1)[1]
                with open(status_path, "w", encoding="utf-8") as stream:
                    stream.write(
                        '{"schema_version":1,"partclone":{"block_size":1024,'
                        '"progress":{"copied_blocks":2,"total_block":4}}}'
                    )
                self.assertIn("--json-fresh=1", argv)
                return FakeProcess(argv, payload)
            artifact = capture_partition(
                "/dev/fake1", "ext4", directory, "part.img", "1",
                {"partclone.ext4": "/usr/bin/partclone.ext4"},
                device_validator=lambda _path: True,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                progress_callback=lambda done, total: progress.append((done, total)),
                popen_factory=factory,
            )
            self.assertEqual(progress, [(2048, 4096)])
            self.assertEqual(artifact.format, "partclone")
            self.assertEqual(os.listdir(directory), ["part.img"])

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
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=factory,
            )
            with open(os.path.join(directory, "part.raw"), "rb") as stream:
                self.assertEqual(stream.read(), b"captured partition bytes")
            self.assertEqual(artifact.format, "raw")
            self.assertEqual(
                sorted(os.listdir(directory)), ["part.raw"]
            )

    def test_progress_callback_receives_byte_count_and_raw_total(self):
        with tempfile.TemporaryDirectory() as directory:
            progress = []
            payload = b"captured partition bytes"
            artifact = capture_partition(
                "/dev/fake1", None, directory, "part.raw", "1",
                {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                expected_size_bytes=len(payload),
                progress_callback=lambda done, total: progress.append((done, total)),
                popen_factory=lambda *_args, **_kwargs: FakeProcess(["dd"], payload),
            )
            self.assertEqual(progress[-1], (len(payload), len(payload)))
            self.assertEqual(artifact.format, "raw")
    def test_cancelling_partition_capture_never_publishes_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = FakeProcess(["dd"], b"partial payload", returncode=None)
            def cancel(_done, _total):
                raise CaptureCancelled("operator cancelled")
            with self.assertRaisesRegex(CaptureCancelled, "cancelled"):
                capture_partition(
                    "/dev/fake1", None, directory, "part.raw", "1",
                    {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                    progress_callback=cancel,
                    popen_factory=lambda *_args, **_kwargs: proc,
                )
            self.assertEqual(os.listdir(directory), [])
            self.assertTrue(proc.terminated)
    def test_failed_producer_does_not_publish_partial_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = FakeProcess(["/usr/bin/dd"], returncode=1)
            with self.assertRaisesRegex(CaptureError, "status 1"):
                capture_partition(
                    "/dev/fake1", None, directory, "part.raw", "1",
                    {"dd": "/usr/bin/dd"}, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
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
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
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
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                    popen_factory=lambda *_args, **_kwargs: FakeProcess(["dd"]),
                )


if __name__ == "__main__":
    unittest.main()
