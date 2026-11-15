import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.image_manifest import ImageManifest
from feclora.storage.disk_restore import DiskRestoreError, _restore_qcow2_disk


class QCOW2DiskRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = Path(self.temp.name)
        self.payload = b"verified qcow2 source"
        (self.repository / "disk.qcow2").write_bytes(self.payload)
        self.manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": "qcow2-image", "image_type": "disk",
            "source_size_bytes": 4096, "logical_sector_size": 512, "partition_table": "gpt",
            "artifacts": [
                {"filename": "disk.qcow2", "role": "disk-image", "format": "qcow2",
                 "compression": "none", "size_bytes": len(self.payload),
                 "sha256": hashlib.sha256(self.payload).hexdigest()},
                {"filename": "table.sfdisk", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": 1, "sha256": "a" * 64},
            ],
        })

    def runner(self, command, **_kwargs):
        if command[1] == "info":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"format": "qcow2", "virtual-size": 4096}),
                stderr="",
            )
        if command[1] == "convert":
            Path(command[-1]).write_bytes(b"r" * 4096)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_verified_qcow2_is_converted_and_dispatched_as_raw_manifest(self):
        def inspect_raw_restore(manifest_path, repository, target, **kwargs):
            raw_manifest = ImageManifest.from_json(Path(manifest_path).read_text(encoding="utf-8"))
            disk = next(item for item in raw_manifest.artifacts if item.role == "disk-image")
            self.assertEqual(disk.format, "raw")
            self.assertEqual(disk.size_bytes, 4096)
            self.assertEqual(target, "/dev/fake")
            self.assertTrue((Path(repository) / disk.filename).is_file())
            return raw_manifest

        with patch("feclora.storage.disk_restore.restore_disk", side_effect=inspect_raw_restore) as restore:
            result = _restore_qcow2_disk(
                self.manifest, str(self.repository), "/dev/fake",
                confirmation="ERASE /dev/fake", initial_device_number=None,
                executables={"qemu-img": "/usr/bin/qemu-img"},
                device_validator=None, runner=self.runner, popen_factory=None,
                target_safety_check=None, effective_uid=None, progress_callback=None,
                age_identity_file="/keys/client.age", age_passphrase=None, pre_write_callback=None,
            )
        self.assertEqual(result.image_id, "qcow2-image")
        self.assertEqual(next(item for item in result.artifacts if item.role == "disk-image").format, "qcow2")
        restore.assert_called_once()

    def test_backing_file_is_rejected_before_qcow2_check_or_conversion(self):
        commands = []
        def backing_runner(command, **_kwargs):
            commands.append(command[1])
            if command[1] == "info":
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({
                        "format": "qcow2", "virtual-size": 4096,
                        "backing-filename": "/etc/passwd",
                    }),
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("feclora.storage.disk_restore.restore_disk") as restore:
            with self.assertRaisesRegex(DiskRestoreError, "dependencies"):
                _restore_qcow2_disk(
                    self.manifest, str(self.repository), "/dev/fake",
                    confirmation="ERASE /dev/fake", initial_device_number=None,
                    executables={"qemu-img": "/usr/bin/qemu-img"},
                    device_validator=None, runner=backing_runner, popen_factory=None,
                    target_safety_check=None, effective_uid=None, progress_callback=None,
                    age_identity_file=None, age_passphrase=None, pre_write_callback=None,
                )
        self.assertEqual(commands, ["info"])
        restore.assert_not_called()

    def test_qcow2_virtual_size_mismatch_is_rejected_before_restore(self):
        def bad_runner(command, **_kwargs):
            if command[1] == "info":
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"format": "qcow2", "virtual-size": 8192}),
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("feclora.storage.disk_restore.restore_disk") as restore:
            with self.assertRaisesRegex(DiskRestoreError, "virtual capacity"):
                _restore_qcow2_disk(
                    self.manifest, str(self.repository), "/dev/fake",
                    confirmation="ERASE /dev/fake", initial_device_number=None,
                    executables={"qemu-img": "/usr/bin/qemu-img"},
                    device_validator=None, runner=bad_runner, popen_factory=None,
                    target_safety_check=None, effective_uid=None, progress_callback=None,
                    age_identity_file=None, age_passphrase=None, pre_write_callback=None,
                )
        restore.assert_not_called()


if __name__ == "__main__":
    unittest.main()
