import unittest
from types import SimpleNamespace

from feclora.storage.filesystem_probe import (
    FilesystemProbeError, probe_ext_minimum_size, probe_ntfs_minimum_size,
)


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

    def test_builds_plan_using_ext_probe_and_keeps_other_filesystems_fixed(self):
        from feclora.storage.filesystem_probe import build_proportional_gpt_plan

        calls = []
        def probe(path, **kwargs):
            calls.append((path, kwargs["filesystem_type"]))
            return 1024 * 1024 * 1024

        plan = build_proportional_gpt_plan(
            [
                {"node": "/dev/source1", "start": 2048, "size": 2_000_000,
                 "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
                {"node": "/dev/source2", "start": 2_100_000, "size": 6_000_000,
                 "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"},
            ],
            source_size_bytes=8_499_999_744,
            target_size_bytes=5_000_000_000,
            sector_size=512,
            partition_table_type="gpt",
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ext4"},
            minimum_probe=probe,
        )
        self.assertEqual(calls, [("/dev/source2", "ext4")])
        self.assertEqual(plan[0].size_sectors, 2_000_000)
        self.assertLessEqual(plan[1].size_sectors, 6_000_000)

    def test_build_plan_rejects_unknown_filesystem_without_guessing(self):
        from feclora.storage.filesystem_probe import build_proportional_gpt_plan

        with self.assertRaisesRegex(FilesystemProbeError, "unknown"):
            build_proportional_gpt_plan(
                [{"node": "/dev/source1", "start": 2048, "size": 2_000_000,
                  "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"}],
                source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000,
                sector_size=512,
                partition_table_type="gpt",
                filesystem_types={},
                minimum_probe=lambda *_args, **_kwargs: 1,
            )

    def test_build_plan_propagates_ext_probe_failure_closed(self):
        from feclora.storage.filesystem_probe import build_proportional_gpt_plan

        def failed_probe(*_args, **_kwargs):
            raise FilesystemProbeError("filesystem is mounted")

        with self.assertRaisesRegex(FilesystemProbeError, "mounted"):
            build_proportional_gpt_plan(
                [{"node": "/dev/source1", "start": 2048, "size": 2_000_000,
                  "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"}],
                source_size_bytes=8_499_999_744,
                target_size_bytes=5_000_000_000,
                sector_size=512,
                partition_table_type="gpt",
                filesystem_types={"/dev/source1": "ext4"},
                minimum_probe=failed_probe,
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


    def test_device_preview_connects_discovery_to_planner_without_write_authority(self):
        from unittest.mock import patch
        from feclora.storage.filesystem_probe import preview_proportional_gpt_plan_from_disk

        discovered = {
            "disk_path": "/dev/sda",
            "source_size_bytes": 8_499_999_744,
            "sector_size": 512,
            "partition_table_type": "gpt",
            "first_usable_lba": 34,
            "last_usable_lba": 8_499_999_744 // 512 - 34,
            "partitions": [{
                "node": "/dev/sda1", "start": 2048, "size": 8_000_000,
                "type": "0fc63daf-8483-4772-8e79-3d69d8477de4",
            }],
            "filesystem_types": {"/dev/sda1": "ext4"},
        }
        with patch("feclora.storage.gpt_inspection.inspect_gpt_source", return_value=discovered):
            result = preview_proportional_gpt_plan_from_disk(
                "/dev/sda",
                target_size_bytes=5_000_000_000,
                minimum_probe=lambda *_args, **_kwargs: 1024 * 1024 * 1024,
            )
        self.assertEqual(result["source_disk"], "/dev/sda")
        self.assertFalse(result["write_authorized"])
        self.assertEqual(result["target_size_bytes"], 5_000_000_000)
        self.assertEqual(len(result["partitions"]), 1)

class NTFSFilesystemProbeTests(unittest.TestCase):
    def setUp(self):
        self.commands = []

    def runner(self, command, **kwargs):
        self.commands.append(command)
        executable = command[0]
        if executable.endswith("blkid"):
            return SimpleNamespace(stdout="ntfs\n", stderr="")
        if executable.endswith("ntfsresize"):
            return SimpleNamespace(
                stdout="You might resize at 123,456,789 bytes or 123,456,789 bytes (freeing space).\n",
                stderr="",
            )
        if executable.endswith("blockdev"):
            return SimpleNamespace(stdout="1000000000\n", stderr="")
        raise AssertionError(command)

    def probe(self, **kwargs):
        return probe_ntfs_minimum_size(
            "/dev/fake",
            filesystem_type="ntfs",
            executables={
                "blkid": "/sbin/blkid", "ntfsresize": "/sbin/ntfsresize",
                "blockdev": "/sbin/blockdev",
            },
            runner=self.runner,
            device_validator=lambda _path: True,
            safety_check=lambda _path: None,
            effective_uid=lambda: 0,
            **kwargs,
        )

    def test_reports_read_only_minimum_and_never_invokes_resize(self):
        self.assertEqual(self.probe(), 123456789)
        self.assertIn(
            ["/sbin/ntfsresize", "--info", "/dev/fake"],
            self.commands,
        )
        self.assertFalse(any("--size" in command for command in self.commands))

    def test_rejects_ntfs_type_mismatch(self):
        def runner(command, **kwargs):
            if command[0].endswith("blkid"):
                return SimpleNamespace(stdout="ext4\n", stderr="")
            return self.runner(command, **kwargs)
        with self.assertRaisesRegex(FilesystemProbeError, "type mismatch"):
            probe_ntfs_minimum_size(
                "/dev/fake", filesystem_type="ntfs",
                executables={"blkid": "/sbin/blkid", "ntfsresize": "/sbin/ntfsresize",
                             "blockdev": "/sbin/blockdev"},
                runner=runner, device_validator=lambda _path: True,
                safety_check=lambda _path: None, effective_uid=lambda: 0,
            )

    def test_rejects_ambiguous_minimum_output(self):
        def runner(command, **kwargs):
            if command[0].endswith("ntfsresize"):
                return SimpleNamespace(stdout="minimum unknown\n", stderr="")
            return self.runner(command, **kwargs)
        with self.assertRaisesRegex(FilesystemProbeError, "unambiguous minimum"):
            probe_ntfs_minimum_size(
                "/dev/fake", filesystem_type="ntfs",
                executables={"blkid": "/sbin/blkid", "ntfsresize": "/sbin/ntfsresize",
                             "blockdev": "/sbin/blockdev"},
                runner=runner, device_validator=lambda _path: True,
                safety_check=lambda _path: None, effective_uid=lambda: 0,
            )

    def test_planner_uses_ntfs_probe_for_final_partition(self):
        from feclora.storage.filesystem_probe import build_proportional_gpt_plan

        calls = []
        def probe(path, **kwargs):
            calls.append((path, kwargs["filesystem_type"]))
            return 1024 * 1024 * 1024

        partitions = [
            {"node": "/dev/source1", "start": 2048, "size": 2_000_000,
             "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
            {"node": "/dev/source2", "start": 2_100_000, "size": 6_000_000,
             "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"},
        ]
        plan = build_proportional_gpt_plan(
            partitions, source_size_bytes=8_499_999_744,
            target_size_bytes=4_000_000_000, sector_size=512,
            partition_table_type="gpt",
            filesystem_types={"/dev/source1": "vfat", "/dev/source2": "ntfs"},
            ntfs_minimum_probe=probe,
        )
        self.assertEqual(calls, [("/dev/source2", "ntfs")])
        self.assertLess(plan[-1].size_sectors, partitions[-1]["size"])
        self.assertGreaterEqual(plan[-1].size_sectors * 512, 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
