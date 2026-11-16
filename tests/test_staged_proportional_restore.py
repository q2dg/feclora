import hashlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.proportional_staging import StagedRawDiskImage
from feclora.storage.source_safety import SourceSafetyError
from feclora.storage.staged_proportional_restore import (
    StagedProportionalRestoreError,
    restore_staged_proportional_image,
)


class _Process:
    def __init__(self, output=b""):
        self.stdout = io.BytesIO(output)
        self.returncode = 0
    def wait(self):
        return self.returncode
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15


class StagedProportionalRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.chmod(self.temp.name, 0o700)
        self.payload = b"P" * 1024
        self.path = os.path.join(self.temp.name, "disk.raw")
        with open(self.path, "wb") as stream:
            stream.write(self.payload)
        os.chmod(self.path, 0o600)
        self.staged = StagedRawDiskImage(
            self.path, len(self.payload), hashlib.sha256(self.payload).hexdigest()
        )
        self.commands = []
        self.processes = []
        self.runner = lambda command, **kwargs: SimpleNamespace(
            stdout=f"{len(self.payload)} disk 512 0\n"
        )
        self.factory = self._factory

    def _factory(self, command, **kwargs):
        self.commands.append(command)
        process = _Process(self.payload if kwargs.get("stdout") is not None else b"")
        self.processes.append(process)
        return process

    def _restore(self, **kwargs):
        options = {
            "executables": {"dd": "/usr/bin/dd", "lsblk": "/usr/bin/lsblk"},
            "device_validator": lambda _path: True,
            "device_identity": lambda _path: (8, 1),
            "expected_device_identity": (8, 1),
            "runner": self.runner,
            "popen_factory": self.factory,
            "target_safety_check": lambda _path: None,
            "effective_uid": lambda: 0,
        }
        options.update(kwargs)
        return restore_staged_proportional_image(
            self.staged, "/dev/fake", sector_size=512,
            confirmation="ERASE /dev/fake", **options,
        )

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_writes_and_reads_back_exact_staged_bytes(self, _gpt):
        digest = self._restore()
        self.assertEqual(digest, self.staged.sha256)
        self.assertEqual(len(self.processes), 2)
        self.assertTrue(any(arg.startswith("of=/dev/fake") for arg in self.commands[0]))
        self.assertIn("iflag=count_bytes", self.commands[1])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary")
    def test_wrong_confirmation_never_opens_or_writes_target(self, _gpt):
        with self.assertRaisesRegex(StagedProportionalRestoreError, "confirmation"):
            restore_staged_proportional_image(
                self.staged, "/dev/fake", sector_size=512,
                expected_device_identity=(8, 1), confirmation="yes"
            )
        self.assertEqual(self.commands, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_captured_wrong_device_identity_prevents_write(self, _gpt):
        with self.assertRaisesRegex(StagedProportionalRestoreError, "captured during target selection"):
            self._restore(expected_device_identity=(8, 2))
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_logical_sector_size_mismatch_prevents_write(self, _gpt):
        runner = lambda *_args, **_kwargs: SimpleNamespace(
            stdout=f"{len(self.payload)} disk 4096 0\n"
        )
        with self.assertRaisesRegex(StagedProportionalRestoreError, "logical sector size"):
            self._restore(runner=runner)
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_unsafe_destination_prevents_write(self, _gpt):
        def reject(_path):
            raise SourceSafetyError("target is mounted")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "unsafe destination"):
            self._restore(target_safety_check=reject)
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_source_revalidation_failure_prevents_write(self, _gpt):
        def reject_source():
            raise StagedProportionalRestoreError("source identity changed")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "source identity changed"):
            self._restore(pre_write_callback=reject_source)
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_wrong_capacity_prevents_write(self, _gpt):
        runner = lambda *_args, **_kwargs: SimpleNamespace(stdout="999 disk 512 0\n")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "exactly"):
            self._restore(runner=runner)
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_staged_digest_is_checked_before_target_inspection(self, _gpt):
        with open(self.path, "r+b") as stream:
            stream.seek(0)
            stream.write(b"T" * len(self.payload))
        with self.assertRaisesRegex(StagedProportionalRestoreError, "SHA-256"):
            self._restore()
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_destination_identity_is_rechecked_before_write(self, _gpt):
        identities = iter([(8, 1), (8, 2)])
        with self.assertRaisesRegex(StagedProportionalRestoreError, "identity changed"):
            self._restore(device_identity=lambda _path: next(identities))
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_identity_change_after_write_blocks_readback(self, _gpt):
        identities = iter([(8, 1), (8, 1), (8, 2)])
        with self.assertRaisesRegex(StagedProportionalRestoreError, "identity changed after writing"):
            self._restore(device_identity=lambda _path: next(identities))
        self.assertEqual(len(self.processes), 1)

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_short_readback_fails_closed(self, _gpt):
        calls = []
        def factory(command, **kwargs):
            calls.append(command)
            output = self.payload if len(calls) == 1 else self.payload[:-1]
            return _Process(output if kwargs.get("stdout") is not None else b"")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "read-back verification failed"):
            self._restore(popen_factory=factory)
        self.assertEqual(len(calls), 2)

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_readback_nonzero_exit_fails_closed(self, _gpt):
        calls = []
        def factory(command, **kwargs):
            calls.append(command)
            process = _Process(self.payload if kwargs.get("stdout") is not None else b"")
            if len(calls) == 2:
                process.returncode = 1
            return process
        with self.assertRaisesRegex(StagedProportionalRestoreError, "read-back verification failed"):
            self._restore(popen_factory=factory)
        self.assertEqual(len(calls), 2)

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_readback_mismatch_fails_closed(self, _gpt):
        calls = []
        def factory(command, **kwargs):
            calls.append(command)
            output = self.payload if len(calls) == 1 else b"bad readback"
            return _Process(output if kwargs.get("stdout") is not None else b"")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "read-back verification failed"):
            self._restore(popen_factory=factory)
        self.assertEqual(len(calls), 2)


    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": False})
    def test_inconsistent_staged_gpt_copies_prevent_target_write(self, _gpt):
        with self.assertRaisesRegex(StagedProportionalRestoreError, "GPT copies are inconsistent"):
            self._restore()
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_nonzero_destination_writer_exit_reports_partial_modification(self, _gpt):
        calls = []
        def factory(command, **kwargs):
            calls.append(command)
            process = _Process()
            process.returncode = 7
            return process
        with self.assertRaisesRegex(StagedProportionalRestoreError, "partially modified"):
            self._restore(popen_factory=factory)
        self.assertEqual(len(calls), 1)

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_destination_writer_spawn_error_is_reported_without_readback(self, _gpt):
        def fail_spawn(_command, **_kwargs):
            raise OSError("simulated exec failure")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "could not start destination write"):
            self._restore(popen_factory=fail_spawn)
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_destination_identity_probe_failure_after_write_skips_readback(self, _gpt):
        calls = []
        def identity(_path):
            calls.append(1)
            if len(calls) <= 2:
                return (8, 1)
            raise OSError("device disappeared")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "cannot establish destination identity"):
            self._restore(device_identity=identity)
        self.assertEqual(len(self.processes), 1)


    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_cancellation_before_write_never_opens_destination_writer(self, _gpt):
        with self.assertRaisesRegex(StagedProportionalRestoreError, "cancelled before destination write"):
            self._restore(cancellation_requested=lambda: True)
        self.assertEqual(self.processes, [])

    @patch("feclora.storage.staged_proportional_restore.inspect_gpt_binary",
           return_value={"primary_backup_consistent": True})
    def test_cancellation_during_destination_write_terminates_writer_and_reports_partial_disk(self, _gpt):
        class PendingProcess(_Process):
            def __init__(self):
                super().__init__()
                self.poll_count = 0
            def poll(self):
                self.poll_count += 1
                return self.returncode if self.returncode is not None else None
            def terminate(self):
                self.returncode = -15

        calls = []
        def factory(command, **kwargs):
            process = PendingProcess()
            calls.append(process)
            return process
        checks = iter([False, True])
        with self.assertRaisesRegex(StagedProportionalRestoreError, "cancelled during destination write; disk may be partially modified"):
            self._restore(
                popen_factory=factory,
                cancellation_requested=lambda: next(checks, True),
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].returncode, -15)


if __name__ == "__main__":
    unittest.main()
