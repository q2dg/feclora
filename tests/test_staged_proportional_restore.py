import hashlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.proportional_staging import StagedRawDiskImage
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
        pass


class StagedProportionalRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.chmod(self.temp.name, 0o700)
        self.payload = b"prepared staged disk image"
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
                self.staged, "/dev/fake", sector_size=512, confirmation="yes"
            )
        self.assertEqual(self.commands, [])

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
        with open(self.path, "ab") as stream:
            stream.write(b"tamper")
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
    def test_readback_mismatch_fails_closed(self, _gpt):
        calls = []
        def factory(command, **kwargs):
            calls.append(command)
            output = self.payload if len(calls) == 1 else b"bad readback"
            return _Process(output if kwargs.get("stdout") is not None else b"")
        with self.assertRaisesRegex(StagedProportionalRestoreError, "read-back verification failed"):
            self._restore(popen_factory=factory)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
