import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage.image_manifest import ImageArtifact
from feclora.storage.stratis_filesystem_image_capture import (
    StratisFilesystemCaptureError,
    capture_stratis_filesystem_image,
)


POOL_UUID = "11111111-1111-1111-1111-111111111111"
FS_UUID = "22222222-2222-2222-2222-222222222222"


def inventory():
    return {
        "stratis_topology": {
            "status": "available",
            "pools": [{
                "name": "pool-a", "uuid": POOL_UUID,
                "total_physical_bytes": 100 * 1024**3,
                "free_physical_bytes": 80 * 1024**3,
                "filesystems": [{
                    "name": "data", "uuid": FS_UUID,
                    "device": "/dev/stratis/pool-a/data",
                    "mapper_device": "/dev/dm-3",
                    "logical_size_bytes": 8 * 1024**3,
                    "used_bytes": 2 * 1024**3,
                    "free_bytes": 6 * 1024**3,
                }],
            }],
        },
        "devices": [{
            "path": "/dev/dm-3", "type": "dm", "filesystem": "xfs",
            "size_bytes": 8 * 1024**3, "logical_sector_size": 512,
            "mountpoints": [],
        }],
    }


class StratisFilesystemCaptureTests(unittest.TestCase):
    def test_capture_publishes_xfs_filesystem_manifest_with_pool_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = ImageArtifact(
                filename="image.img", role="stratis-filesystem-image",
                format="partclone", compression="none", size_bytes=4096,
                sha256="a" * 64, filesystem="xfs",
            )

            def fake_capture(source, filesystem, stage, filename, partition_id, executables, **kwargs):
                Path(stage, filename).write_bytes(b"image")
                return artifact

            with patch(
                "feclora.storage.stratis_filesystem_image_capture.capture_partition",
                side_effect=fake_capture,
            ) as capture:
                manifest = capture_stratis_filesystem_image(
                    "/dev/dm-3", "image", tmp, inventory(),
                    executables={"partclone.xfs": "/usr/bin/partclone.xfs"},
                    device_validator=lambda _: True,
                    source_safety_check=lambda _: None,
                )
            self.assertEqual(manifest.image_type, "stratis_filesystem")
            self.assertEqual(manifest.storage["stratis_pool_uuid"], POOL_UUID)
            self.assertEqual(manifest.storage["stratis_filesystem_uuid"], FS_UUID)
            self.assertFalse(manifest.storage["dependencies"][0]["included_in_source_bytes"])
            self.assertEqual(capture.call_args.kwargs["artifact_role"], "stratis-filesystem-image")
            self.assertEqual(capture.call_args.kwargs["expected_size_bytes"], 8 * 1024**3)
            self.assertTrue(Path(tmp, "image.manifest.json").exists())
            self.assertTrue(Path(tmp, "image.img").exists())

    def test_rejects_incomplete_stratis_inventory(self):
        value = inventory()
        value["stratis_topology"]["status"] = "metadata_incomplete"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            StratisFilesystemCaptureError, "metadata is unavailable or incomplete"
        ):
            capture_stratis_filesystem_image("/dev/dm-3", "image", tmp, value)

    def test_rejects_non_xfs_source(self):
        value = inventory()
        value["devices"][0]["filesystem"] = "ext4"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            StratisFilesystemCaptureError, "only XFS"
        ):
            capture_stratis_filesystem_image("/dev/dm-3", "image", tmp, value)

    def test_rejects_ambiguous_filesystem_identity(self):
        value = inventory()
        value["stratis_topology"]["pools"][0]["filesystems"].append(
            dict(value["stratis_topology"]["pools"][0]["filesystems"][0])
        )
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            StratisFilesystemCaptureError, "exactly one"
        ):
            capture_stratis_filesystem_image("/dev/dm-3", "image", tmp, value)

    def test_rejects_mounted_source(self):
        value = inventory()
        value["devices"][0]["mountpoints"] = ["/mnt/data"]
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            StratisFilesystemCaptureError, "is mounted"
        ):
            capture_stratis_filesystem_image("/dev/dm-3", "image", tmp, value)

    def test_rejects_raw_fallback_when_partclone_xfs_is_unavailable(self):
        value = inventory()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "feclora.storage.stratis_filesystem_image_capture.shutil.which",
            return_value=None,
        ), self.assertRaisesRegex(StratisFilesystemCaptureError, "raw imaging fallback is disabled"):
            capture_stratis_filesystem_image(
                "/dev/dm-3", "image", tmp, value,
                executables={"dd": "/usr/bin/dd"},
            )

    def test_rejects_disagreement_between_cli_and_block_capacity(self):
        value = inventory()
        value["devices"][0]["size_bytes"] -= 4096
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            StratisFilesystemCaptureError, "disagree"
        ):
            capture_stratis_filesystem_image("/dev/dm-3", "image", tmp, value)


if __name__ == "__main__":
    unittest.main()
