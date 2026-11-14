import hashlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.proportional_staging import StagedRawDiskImage
from feclora.storage.staged_filesystem_shrink import (
    StagedFilesystemShrinkError,
    shrink_staged_ext_filesystem,
)


class StagedExtFilesystemShrinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "disk.raw")
        with open(self.path, "wb") as stream:
            stream.write(b"\0" * (20 * 1024 * 1024))
        os.chmod(self.path, 0o600)
        self.initial_digest = self.digest()
        self.commands = []
        self.block_count = 2000
        self.mapping_valid = True

    def tearDown(self):
        self.temp.cleanup()

    def digest(self):
        with open(self.path, "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()

    def runner(self, command, **kwargs):
        self.commands.append(command)
        args = command
        if args[0].endswith("losetup") and "--find" in args:
            return SimpleNamespace(stdout="/dev/loop7\n", stderr="")
        if args[0].endswith("losetup") and "--list" in args:
            backing = self.path if self.mapping_valid else "/tmp/other.raw"
            return SimpleNamespace(stdout=json.dumps({"loopdevices": [{
                "name": "/dev/loop7", "back-file": backing,
                "offset": 1024 * 1024, "sizelimit": 10 * 1024 * 1024,
            }]}), stderr="")
        if args[0].endswith("losetup") and "--detach" in args:
            return SimpleNamespace(stdout="", stderr="")
        if args[0].endswith("blkid"):
            return SimpleNamespace(stdout="ext4\n", stderr="")
        if args[0].endswith("e2fsck"):
            return SimpleNamespace(stdout="clean\n", stderr="")
        if args[0].endswith("dumpe2fs"):
            return SimpleNamespace(stdout=f"Block size: 4096\nBlock count: {self.block_count}\n", stderr="")
        if args[0].endswith("resize2fs") and "-P" in args:
            return SimpleNamespace(
                stdout="Estimated minimum size of the filesystem: 900\n", stderr=""
            )
        if args[0].endswith("resize2fs"):
            self.block_count = int(args[-1])
            with open(self.path, "r+b") as stream:
                stream.seek(0)
                stream.write(b"F")
            return SimpleNamespace(stdout="resized\n", stderr="")
        raise AssertionError(command)

    def shrink(self, **kwargs):
        staged = StagedRawDiskImage(self.path, os.path.getsize(self.path), self.initial_digest)
        runner_impl = kwargs.pop("runner", self.runner)
        return shrink_staged_ext_filesystem(
            staged,
            partition_start_sector=2048,
            source_partition_size_sectors=20480,
            target_partition_size_bytes=5 * 1024 * 1024,
            target_filesystem_size_bytes=1000 * 4096,
            sector_size=512,
            executables={name: "/sbin/" + name for name in
                         ("losetup", "blkid", "e2fsck", "dumpe2fs", "resize2fs")},
            runner=runner_impl,
            which=lambda _name: None,
            block_device_validator=lambda _path: True,
            safety_check=lambda _path: None,
            effective_uid=lambda: 0,
            **kwargs,
        )

    def test_shrinks_only_loop_slice_and_verifies_filesystem(self):
        result = self.shrink()
        self.assertEqual(result.size_bytes, 20 * 1024 * 1024)
        self.assertNotEqual(result.sha256, self.initial_digest)
        self.assertIn(
            ["/sbin/resize2fs", "/dev/loop7", "1000"],
            self.commands,
        )
        self.assertIn(["/sbin/losetup", "--detach", "/dev/loop7"], self.commands)
        self.assertEqual(
            self.commands[0],
            ["/sbin/losetup", "--find", "--show", "--offset", str(1024 * 1024),
             "--sizelimit", str(10 * 1024 * 1024), self.path],
        )

    def test_rejects_loop_mapping_to_different_backing_file(self):
        self.mapping_valid = False
        with self.assertRaisesRegex(StagedFilesystemShrinkError, "mapping failed"):
            self.shrink()
        self.assertIn(["/sbin/losetup", "--detach", "/dev/loop7"], self.commands)
        self.assertFalse(any(command[0].endswith("resize2fs") for command in self.commands))

    def test_rejects_filesystem_type_before_mutation(self):
        original = self.runner
        def runner(command, **kwargs):
            if command[0].endswith("blkid"):
                self.commands.append(command)
                return SimpleNamespace(stdout="xfs\n", stderr="")
            return original(command, **kwargs)
        with self.assertRaisesRegex(StagedFilesystemShrinkError, "supports ext2/3/4"):
            self.shrink(runner=runner)
        self.assertFalse(any(command[0].endswith("resize2fs") for command in self.commands))

    def test_rejects_modified_staged_image_before_loop_setup(self):
        with open(self.path, "r+b") as stream:
            stream.write(b"X")
        with self.assertRaisesRegex(StagedFilesystemShrinkError, "digest mismatch"):
            self.shrink()
        self.assertEqual(self.commands, [])

    def test_rejects_filesystem_target_larger_than_planned_partition(self):
        staged = StagedRawDiskImage(self.path, os.path.getsize(self.path), self.initial_digest)
        with self.assertRaisesRegex(StagedFilesystemShrinkError, "exceeds"):
            shrink_staged_ext_filesystem(
                staged, partition_start_sector=2048,
                source_partition_size_sectors=20480,
                target_partition_size_bytes=4 * 1024 * 1024,
                target_filesystem_size_bytes=5 * 1024 * 1024,
                sector_size=512,
            )


if __name__ == "__main__":
    unittest.main()
