import hashlib
import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.proportional_staging import StagedRawDiskImage
from feclora.storage.staged_ntfs_shrink import (
    StagedNTFSShrinkError,
    shrink_staged_ntfs_filesystem,
)


class StagedNTFSShrinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "disk.raw")
        with open(self.path, "wb") as stream:
            stream.write(b"\0" * (20 * 1024 * 1024))
        os.chmod(self.path, 0o600)
        self.initial_digest = self.digest()
        self.commands = []
        self.current_bytes = 8 * 1024 * 1024
        self.minimum_bytes = 4 * 1024 * 1024
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
            return SimpleNamespace(stdout="/dev/loop8\n", stderr="")
        if args[0].endswith("losetup") and "--list" in args:
            backing = self.path if self.mapping_valid else "/tmp/other.raw"
            return SimpleNamespace(stdout=json.dumps({"loopdevices": [{
                "name": "/dev/loop8", "back-file": backing,
                "offset": 1024 * 1024, "sizelimit": 10 * 1024 * 1024,
            }]}), stderr="")
        if args[0].endswith("losetup") and "--detach" in args:
            return SimpleNamespace(stdout="", stderr="")
        if args[0].endswith("blkid"):
            return SimpleNamespace(stdout="ntfs\n", stderr="")
        if args[0].endswith("blockdev"):
            return SimpleNamespace(stdout=str(10 * 1024 * 1024) + "\n", stderr="")
        if args[0].endswith("ntfsresize") and "--info" in args:
            return SimpleNamespace(
                stdout=(
                    f"Current volume size: {self.current_bytes:,} bytes\n"
                    f"You might resize at {self.minimum_bytes:,} bytes or less\n"
                ),
                stderr="",
            )
        if args[0].endswith("ntfsresize") and "--size" in args:
            self.current_bytes = int(args[args.index("--size") + 1])
            with open(self.path, "r+b") as stream:
                stream.write(b"N")
            return SimpleNamespace(stdout="resize complete\n", stderr="")
        raise AssertionError(command)

    def shrink(self, **kwargs):
        staged = StagedRawDiskImage(self.path, os.path.getsize(self.path), self.initial_digest)
        runner_impl = kwargs.pop("runner", self.runner)
        return shrink_staged_ntfs_filesystem(
            staged,
            partition_start_sector=2048,
            source_partition_size_sectors=20480,
            target_partition_size_bytes=6 * 1024 * 1024,
            target_filesystem_size_bytes=5 * 1024 * 1024,
            sector_size=512,
            executables={name: "/sbin/" + name for name in
                         ("losetup", "blkid", "ntfsresize", "blockdev")},
            runner=runner_impl,
            which=lambda _name: None,
            block_device_validator=lambda _path: True,
            safety_check=lambda _path: None,
            effective_uid=lambda: 0,
            **kwargs,
        )

    def test_shrinks_ntfs_only_inside_verified_loop_slice(self):
        result = self.shrink()
        self.assertEqual(result.size_bytes, 20 * 1024 * 1024)
        self.assertNotEqual(result.sha256, self.initial_digest)
        self.assertIn(
            ["/sbin/ntfsresize", "--size", str(5 * 1024 * 1024), "/dev/loop8"],
            self.commands,
        )
        self.assertIn(["/sbin/losetup", "--detach", "/dev/loop8"], self.commands)
        self.assertEqual(
            self.commands[0],
            ["/sbin/losetup", "--find", "--show", "--offset", str(1024 * 1024),
             "--sizelimit", str(10 * 1024 * 1024), self.path],
        )

    def test_rejects_wrong_loop_backing_file(self):
        self.mapping_valid = False
        with self.assertRaisesRegex(StagedNTFSShrinkError, "mapping failed"):
            self.shrink()
        self.assertIn(["/sbin/losetup", "--detach", "/dev/loop8"], self.commands)
        self.assertFalse(any("--size" in command for command in self.commands))

    def test_rejects_non_ntfs_signature(self):
        original = self.runner
        def runner(command, **kwargs):
            if command[0].endswith("blkid"):
                self.commands.append(command)
                return SimpleNamespace(stdout="ext4\n", stderr="")
            return original(command, **kwargs)
        with self.assertRaisesRegex(StagedNTFSShrinkError, "requires NTFS"):
            self.shrink(runner=runner)
        self.assertFalse(any("--size" in command for command in self.commands))

    def test_rejects_target_below_live_staged_minimum(self):
        self.minimum_bytes = 6 * 1024 * 1024
        with self.assertRaisesRegex(StagedNTFSShrinkError, "below the staged filesystem minimum"):
            self.shrink()
        self.assertFalse(any("--size" in command for command in self.commands))
        self.assertIn(["/sbin/losetup", "--detach", "/dev/loop8"], self.commands)

    def test_rejects_modified_staged_raw_before_loop_setup(self):
        with open(self.path, "r+b") as stream:
            stream.write(b"X")
        with self.assertRaisesRegex(StagedNTFSShrinkError, "digest mismatch"):
            self.shrink()
        self.assertEqual(self.commands, [])

    def test_rejects_target_larger_than_planned_partition(self):
        staged = StagedRawDiskImage(self.path, os.path.getsize(self.path), self.initial_digest)
        with self.assertRaisesRegex(StagedNTFSShrinkError, "exceeds"):
            shrink_staged_ntfs_filesystem(
                staged, partition_start_sector=2048,
                source_partition_size_sectors=20480,
                target_partition_size_bytes=4 * 1024 * 1024,
                target_filesystem_size_bytes=5 * 1024 * 1024,
                sector_size=512,
            )


if __name__ == "__main__":
    unittest.main()
