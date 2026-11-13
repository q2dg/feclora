import unittest
from types import SimpleNamespace

from feclora.storage.filesystem_probe import FilesystemProbeError, probe_ext_minimum_size


class ExtFilesystemProbeTests(unittest.TestCase):
    def setUp(self):
        self.commands = []

    def runner(self, command, **kwargs):
        self.commands.append(command)
        executable = command[0]
        if executable.endswith("blkid"):
            return SimpleNamespace(stdout="ext4\n", stderr="")
        if executable.endswith("e2fsck"):
            return SimpleNamespace(stdout="clean\n", stderr="")
        if executable.endswith("dumpe2fs"):
            return SimpleNamespace(stdout="Block size: 4096\n", stderr="")
        if executable.endswith("resize2fs"):
            return SimpleNamespace(stdout="Estimated minimum size of the filesystem: 100000\n", stderr="")
        if executable.endswith("blockdev"):
            return SimpleNamespace(stdout="1000000000\n", stderr="")
        raise AssertionError(command)

    def probe(self, **kwargs):
        return probe_ext_minimum_size(
            "/dev/fake",
            filesystem_type="ext4",
            executables={
                "blkid": "/sbin/blkid", "e2fsck": "/sbin/e2fsck",
                "dumpe2fs": "/sbin/dumpe2fs", "resize2fs": "/sbin/resize2fs",
                "blockdev": "/sbin/blockdev",
            },
            runner=self.runner,
            device_validator=lambda _path: True,
            safety_check=lambda _path: None,
            effective_uid=lambda: 0,
            **kwargs,
        )

    def test_reports_read_only_minimum_in_bytes(self):
        self.assertEqual(self.probe(), 409600000)
        self.assertIn(["/sbin/e2fsck", "-f", "-n", "/dev/fake"], self.commands)
        self.assertIn(["/sbin/resize2fs", "-P", "/dev/fake"], self.commands)

    def test_rejects_filesystem_type_mismatch_before_resize_probe(self):
        def runner(command, **kwargs):
            if command[0].endswith("blkid"):
                return SimpleNamespace(stdout="xfs\n", stderr="")
            return self.runner(command, **kwargs)
        with self.assertRaisesRegex(FilesystemProbeError, "type mismatch"):
            probe_ext_minimum_size(
                "/dev/fake", filesystem_type="ext4",
                executables={"blkid": "/sbin/blkid", "e2fsck": "/sbin/e2fsck",
                             "dumpe2fs": "/sbin/dumpe2fs", "resize2fs": "/sbin/resize2fs",
                             "blockdev": "/sbin/blockdev"},
                runner=runner, device_validator=lambda _path: True,
                safety_check=lambda _path: None, effective_uid=lambda: 0,
            )

    def test_rejects_minimum_larger_than_partition(self):
        def runner(command, **kwargs):
            if command[0].endswith("blockdev"):
                return SimpleNamespace(stdout="1000\n", stderr="")
            return self.runner(command, **kwargs)
        with self.assertRaisesRegex(FilesystemProbeError, "exceeds"):
            probe_ext_minimum_size(
                "/dev/fake", filesystem_type="ext4",
                executables={"blkid": "/sbin/blkid", "e2fsck": "/sbin/e2fsck",
                             "dumpe2fs": "/sbin/dumpe2fs", "resize2fs": "/sbin/resize2fs",
                             "blockdev": "/sbin/blockdev"},
                runner=runner, device_validator=lambda _path: True,
                safety_check=lambda _path: None, effective_uid=lambda: 0,
            )

    def test_rejects_non_ext_filesystem(self):
        with self.assertRaisesRegex(FilesystemProbeError, "only ext2"):
            probe_ext_minimum_size(
                "/dev/fake", filesystem_type="xfs",
                executables={}, runner=self.runner, device_validator=lambda _path: True,
                safety_check=lambda _path: None, effective_uid=lambda: 0,
            )

    def test_runs_safety_check_before_any_probe(self):
        def unsafe(_path):
            from feclora.storage.source_safety import SourceSafetyError
            raise SourceSafetyError("mounted")
        with self.assertRaisesRegex(FilesystemProbeError, "offline and unused"):
            probe_ext_minimum_size(
                "/dev/fake", filesystem_type="ext4",
                executables={"blkid": "/sbin/blkid", "e2fsck": "/sbin/e2fsck",
                             "dumpe2fs": "/sbin/dumpe2fs", "resize2fs": "/sbin/resize2fs",
                             "blockdev": "/sbin/blockdev"},
                runner=self.runner, device_validator=lambda _path: True,
                safety_check=unsafe, effective_uid=lambda: 0,
            )
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
