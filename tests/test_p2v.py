import json
import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from feclora.storage.p2v import P2VError, convert_block_device_to_qcow2


class P2VConversionTests(unittest.TestCase):
    def setUp(self):
        self.source_info = SimpleNamespace(
            st_mode=stat.S_IFBLK | 0o600, st_rdev=2049, st_ino=77,
        )
        self.stat_device = Mock(return_value=self.source_info)
        self.source_safety = Mock()
        self.calls = []

    def runner(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:3] == ["--getsize64", "/dev/feclora-test"]:
            return SimpleNamespace(returncode=0, stdout="4096\n", stderr="")
        if argv[1] == "convert":
            with open(argv[-1], "wb") as stream:
                stream.write(b"qcow2-test-payload")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[1] == "check":
            return SimpleNamespace(returncode=0, stdout="No errors were found", stderr="")
        if argv[1:3] == ["info", "--output=json"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"format": "qcow2", "virtual-size": 4096}),
                stderr="",
            )
        raise AssertionError(argv)

    def test_converts_and_verifies_qcow2_without_touching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            output = os.path.join(directory, "physical-machine.qcow2")
            result = convert_block_device_to_qcow2(
                "/dev/feclora-test", output, qemu_img="/usr/bin/qemu-img",
                blockdev="/usr/sbin/blockdev", runner=self.runner,
                stat_device=self.stat_device, source_safety_check=self.source_safety,
            )
            self.assertTrue(result["verified"])
            self.assertEqual(result["virtual_size_bytes"], 4096)
            self.assertEqual(result["format"], "qcow2")
            self.assertTrue(os.path.isfile(output))
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            self.assertEqual([call[1] for call in self.calls], ["--getsize64", "convert", "check", "info"])
            self.source_safety.assert_called_with("/dev/feclora-test")
            self.assertEqual(self.stat_device.call_count, 2)

    def test_rejects_non_block_source(self):
        self.stat_device.return_value = SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_rdev=0, st_ino=77,
        )
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            with self.assertRaisesRegex(P2VError, "physical block device"):
                convert_block_device_to_qcow2(
                    "/dev/regular-file", os.path.join(directory, "disk.qcow2"),
                    stat_device=self.stat_device, source_safety_check=self.source_safety,
                )

    def test_never_overwrites_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            output = os.path.join(directory, "disk.qcow2")
            with open(output, "wb") as stream:
                stream.write(b"keep")
            with self.assertRaisesRegex(P2VError, "overwrite"):
                convert_block_device_to_qcow2(
                    "/dev/feclora-test", output, stat_device=self.stat_device,
                    source_safety_check=self.source_safety,
                )
            with open(output, "rb") as stream:
                self.assertEqual(stream.read(), b"keep")

    def test_rejects_qcow2_with_wrong_virtual_capacity(self):
        def runner(argv, **kwargs):
            if argv[1:3] == ["--getsize64", "/dev/feclora-test"]:
                return SimpleNamespace(returncode=0, stdout="4096", stderr="")
            if argv[1] == "convert":
                with open(argv[-1], "wb") as stream:
                    stream.write(b"payload")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[1] == "check":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[1:3] == ["info", "--output=json"]:
                return SimpleNamespace(returncode=0, stdout='{"format":"qcow2","virtual-size":2048}', stderr="")
            raise AssertionError(argv)

        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            output = os.path.join(directory, "disk.qcow2")
            with self.assertRaisesRegex(P2VError, "capacity"):
                convert_block_device_to_qcow2(
                    "/dev/feclora-test", output, qemu_img="/usr/bin/qemu-img",
                    blockdev="/usr/sbin/blockdev", runner=runner,
                    stat_device=self.stat_device, source_safety_check=self.source_safety,
                )
            self.assertFalse(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()
