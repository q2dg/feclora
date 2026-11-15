import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.image_manifest import ImageManifest
from feclora.storage.qcow2_disk_capture import QCOW2CaptureError, capture_qcow2_disk


class QCOW2DiskCaptureTests(unittest.TestCase):
    def test_rejects_path_like_image_identifier_before_conversion(self):
        with tempfile.TemporaryDirectory() as repository:
            with patch("feclora.storage.qcow2_disk_capture.convert_block_device_to_qcow2") as convert:
                with self.assertRaisesRegex(QCOW2CaptureError, "safe identifier"):
                    capture_qcow2_disk("/dev/fake", "../outside", repository)
            convert.assert_not_called()

    def test_capture_publishes_qcow2_as_a_normal_disk_image_set(self):
        with tempfile.TemporaryDirectory() as repository:
            def convert(_source, output, **_kwargs):
                Path(output).write_bytes(b"verified qcow2")
                return {
                    "virtual_size_bytes": 4096,
                    "logical_sector_size": 512,
                    "file_size_bytes": len(b"verified qcow2"),
                }

            def runner(command, **_kwargs):
                if command[0] == "/usr/bin/lsblk":
                    return SimpleNamespace(stdout="4096 512 gpt\n")
                if command[0] == "/usr/bin/sfdisk":
                    return SimpleNamespace(stdout="label: gpt\nunit: sectors\n")
                self.fail(f"unexpected command: {command}")

            with patch("feclora.storage.qcow2_disk_capture.convert_block_device_to_qcow2", side_effect=convert), \
                 patch("feclora.storage.qcow2_disk_capture.shutil.which",
                       side_effect=lambda name: {"lsblk": "/usr/bin/lsblk", "sfdisk": "/usr/bin/sfdisk"}.get(name)), \
                 patch("feclora.storage.qcow2_disk_capture.privileged_argv", side_effect=lambda command: command):
                manifest = capture_qcow2_disk("/dev/fake", "qcow2-image", repository, runner=runner)

            self.assertEqual(manifest.image_type, "disk")
            disk = next(item for item in manifest.artifacts if item.role == "disk-image")
            self.assertEqual(disk.format, "qcow2")
            self.assertEqual(disk.compression, "none")
            self.assertTrue((Path(repository) / disk.filename).is_file())
            saved = ImageManifest.from_json(
                (Path(repository) / "qcow2-image.manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved, manifest)
            self.assertTrue((Path(repository) / "qcow2-image.sfdisk").is_file())


if __name__ == "__main__":
    unittest.main()
