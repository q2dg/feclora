import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.ddrescue_recovery import (
    DdrescueRecoveryError,
    parse_ddrescue_mapfile,
    recover_block_device,
)


class DdrescueMapfileTests(unittest.TestCase):
    def test_parses_complete_mapfile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "map")
            with open(path, "w", encoding="ascii") as stream:
                stream.write("# Mapfile. Created by GNU ddrescue\n0x0 0x100 +\n")
            summary = parse_ddrescue_mapfile(path, 256)
            self.assertTrue(summary.complete)
            self.assertEqual(summary.rescued_bytes, 256)

    def test_parses_degraded_mapfile_and_rejects_uncovered_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "map")
            with open(path, "w", encoding="ascii") as stream:
                stream.write("0x0 0x80 +\n0x80 0x80 -\n")
            summary = parse_ddrescue_mapfile(path, 256)
            self.assertFalse(summary.complete)
            self.assertEqual(summary.bad_sector_bytes, 128)
            with open(path, "w", encoding="ascii") as stream:
                stream.write("0x0 0x80 +\n")
            with self.assertRaisesRegex(DdrescueRecoveryError, "does not cover"):
                parse_ddrescue_mapfile(path, 256)


class DdrescueRecoveryTests(unittest.TestCase):
    def _runner(self, map_status):
        def run(command, **_kwargs):
            with open(command[-1], "w", encoding="ascii") as stream:
                stream.write(map_status)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return run

    def test_complete_recovery_retains_mapfile_and_marks_job_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            result = recover_block_device(
                "/dev/test", "disk-recovery", directory,
                source_size_bytes=256, source_identity="8:0",
                executables={"ddrescue": "/usr/bin/ddrescue"},
                runner=self._runner("0x0 0x100 +\n"),
                device_validator=lambda _path: True,
                identity_reader=lambda _path: "8:0",
                source_safety_check=lambda _path: None,
            )
            self.assertEqual(result.state, "completed")
            self.assertEqual(result.summary.rescued_bytes, 256)
            self.assertTrue(os.path.isfile(result.mapfile_path))
            with open(os.path.join(directory, ".feclora-recovery-disk-recovery", "job.json"),
                      encoding="utf-8") as stream:
                self.assertEqual(json.load(stream)["state"], "completed")

    def test_runs_direct_retry_pass_after_incomplete_first_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []
            maps = ["0x0 0x80 +\\n0x80 0x80 -\\n", "0x0 0x100 +\\n"]
            def run(command, **_kwargs):
                commands.append(command)
                with open(command[-1], "w", encoding="ascii") as stream:
                    stream.write(maps.pop(0))
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            result = recover_block_device(
                "/dev/test", "retry-job", directory, source_size_bytes=256,
                source_identity="8:0", retry_passes=2,
                executables={"ddrescue": "/usr/bin/ddrescue"}, runner=run,
                device_validator=lambda _path: True,
                identity_reader=lambda _path: "8:0",
                source_safety_check=lambda _path: None,
            )
            self.assertEqual(result.state, "completed")
            self.assertEqual(len(commands), 2)
            self.assertIn("--no-scrape", commands[0])
            self.assertIn("--direct", commands[1])
            self.assertIn("--retry-passes=2", commands[1])

    def test_degraded_recovery_can_resume_with_same_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            kwargs = dict(
                source_path="/dev/test", job_id="disk-recovery", repository=directory,
                source_size_bytes=256, source_identity="8:0",
                executables={"ddrescue": "/usr/bin/ddrescue"},
                device_validator=lambda _path: True,
                identity_reader=lambda _path: "8:0",
                source_safety_check=lambda _path: None,
            )
            first = recover_block_device(
                **kwargs, retry_passes=0,
                runner=self._runner("0x0 0x80 +\n0x80 0x80 -\n"),
            )
            self.assertEqual(first.state, "degraded")
            resumed = recover_block_device(
                **kwargs, retry_passes=0, resume=True,
                runner=self._runner("0x0 0x100 +\n"),
            )
            self.assertEqual(resumed.state, "completed")
            self.assertEqual(resumed.summary.bad_sector_bytes, 0)

    def test_resume_rejects_different_kernel_device_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            kwargs = dict(
                source_path="/dev/test", job_id="disk-recovery", repository=directory,
                source_size_bytes=256, source_identity="8:0",
                executables={"ddrescue": "/usr/bin/ddrescue"},
                device_validator=lambda _path: True,
                identity_reader=lambda _path: "8:0",
                source_safety_check=lambda _path: None,
                retry_passes=0, runner=self._runner("0x0 0x100 +\n"),
            )
            recover_block_device(**kwargs)
            with self.assertRaisesRegex(DdrescueRecoveryError, "identity changed"):
                recover_block_device(
                    **{**kwargs, "identity_reader": lambda _path: "8:1"}, resume=True,
                )

    def test_rejects_resume_with_different_source_size(self):
        with tempfile.TemporaryDirectory() as directory:
            kwargs = dict(
                source_path="/dev/test", job_id="disk-recovery", repository=directory,
                source_size_bytes=256, source_identity="8:0",
                executables={"ddrescue": "/usr/bin/ddrescue"},
                device_validator=lambda _path: True,
                identity_reader=lambda _path: "8:0",
                source_safety_check=lambda _path: None,
                retry_passes=0, runner=self._runner("0x0 0x100 +\n"),
            )
            recover_block_device(**kwargs)
            with self.assertRaisesRegex(DdrescueRecoveryError, "source_size_bytes"):
                recover_block_device(**{**kwargs, "source_size_bytes": 512}, resume=True)


if __name__ == "__main__":
    unittest.main()
