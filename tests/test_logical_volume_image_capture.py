import os
import tempfile
import unittest
from unittest.mock import patch

from feclora.storage.image_manifest import ImageArtifact
from feclora.storage.logical_volume_image_capture import (
    LogicalVolumeImageCaptureError,
    capture_logical_volume_image,
)


def make_inventory():
    return {
        "devices": [{
            "path": "/dev/vg/root", "type": "lvm", "size_bytes": 4096,
            "logical_sector_size": 512, "filesystem": "ext4",
            "major_minor": "253:4", "children": [],
        }],
        "volume_topology": {
            "status": "available",
            "volume_groups": [{
                "name": "vg", "status": "healthy",
                "logical_volumes": [{
                    "path": "/dev/vg/root", "size_bytes": 4096,
                    "major_minor": "253:4", "hidden": False,
                    "snapshot": False, "health": None,
                }],
            }],
        },
    }


def make_plan(blockers=None):
    return {
        "source": {
            "path": "/dev/vg/root", "type": "logical_volume",
            "size_bytes": 4096, "filesystem": "ext4",
        },
        "manifest_storage": {
            "schema_version": 1,
            "capture_scope": "logical_volume_bytes",
            "source_layer": "lvm_logical_volume",
            "lvm_vg_name": "vg", "lvm_lv_name": "root",
            "dependencies": [{
                "kind": "lvm_volume_group", "identity": "vg",
                "included_in_source_bytes": False,
            }],
        },
        "blockers": blockers or [],
    }


class LogicalVolumeImageCaptureTests(unittest.TestCase):
    def test_creates_manifest_backed_logical_volume_image(self):
        with tempfile.TemporaryDirectory() as repository:
            def capture(_source, _filesystem, stage, filename, *_args, **_kwargs):
                with open(os.path.join(stage, filename), "wb") as stream:
                    stream.write(b"image")
                return ImageArtifact(
                    filename=filename, role="logical-volume-image",
                    format="raw", compression="none", size_bytes=5,
                    sha256="a" * 64,
                )

            with patch(
                "feclora.storage.logical_volume_image_capture.plan_storage_capture",
                return_value=make_plan(),
            ), patch(
                "feclora.storage.logical_volume_image_capture.capture_logical_volume",
                side_effect=capture,
            ):
                manifest = capture_logical_volume_image(
                    "/dev/vg/root", "root-image", repository, make_inventory(),
                )
            self.assertEqual(manifest.image_type, "logical_volume")
            self.assertEqual(manifest.artifacts[0].role, "logical-volume-image")
            self.assertEqual(manifest.storage["lvm_vg_name"], "vg")
            self.assertTrue(os.path.isfile(os.path.join(repository, "root-image.img")))
            self.assertTrue(os.path.isfile(os.path.join(repository, "root-image.manifest.json")))

    def test_rejects_blocked_storage_plan_before_capture(self):
        with tempfile.TemporaryDirectory() as repository:
            with patch(
                "feclora.storage.logical_volume_image_capture.plan_storage_capture",
                return_value=make_plan(["volume group is incomplete"]),
            ), patch(
                "feclora.storage.logical_volume_image_capture.capture_logical_volume",
            ) as capture:
                with self.assertRaisesRegex(LogicalVolumeImageCaptureError, "incomplete"):
                    capture_logical_volume_image(
                        "/dev/vg/root", "root-image", repository, make_inventory(),
                    )
                capture.assert_not_called()

    def test_rejects_unknown_logical_sector_size(self):
        with tempfile.TemporaryDirectory() as repository:
            inventory = make_inventory()
            inventory["devices"][0]["logical_sector_size"] = None
            with patch(
                "feclora.storage.logical_volume_image_capture.plan_storage_capture",
                return_value=make_plan(),
            ):
                with self.assertRaisesRegex(LogicalVolumeImageCaptureError, "sector size"):
                    capture_logical_volume_image(
                        "/dev/vg/root", "root-image", repository, inventory,
                    )


if __name__ == "__main__":
    unittest.main()
