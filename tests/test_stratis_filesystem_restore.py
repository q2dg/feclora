import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.storage.image_manifest import ImageManifest
from feclora.storage.stratis_filesystem_restore import (
    StratisFilesystemRestoreError,
    restore_stratis_filesystem_image,
)


SOURCE_FS_UUID = "11111111-1111-1111-1111-111111111111"
TARGET_POOL_UUID = "33333333-3333-3333-3333-333333333333"
TARGET_FS_UUID = "44444444-4444-4444-4444-444444444444"
SIZE = 8 * 1024**3
TARGET_SIZE = 16 * 1024**3


def target_inventory(filesystem_uuid=TARGET_FS_UUID, mountpoints=None, size=TARGET_SIZE):
    return {
        "stratis_topology": {
            "status": "available",
            "pools": [{
                "name": "pool-target", "uuid": TARGET_POOL_UUID, "alerts_reported": False,
                "filesystems": [{
                    "name": "restore-target", "uuid": filesystem_uuid,
                    "device": "/dev/stratis/pool-target/restore-target",
                    "mapper_device": "/dev/dm-9",
                    "logical_size_bytes": size, "used_bytes": 0,
                }],
            }],
        },
        "devices": [{
            "path": "/dev/dm-9", "type": "dm", "filesystem": "xfs",
            "size_bytes": size, "logical_sector_size": 512,
            "major_minor": "253:9", "mountpoints": mountpoints or [],
        }],
    }


class FakeProcess:
    def wait(self):
        return 0


class StratisFilesystemRestoreTests(unittest.TestCase):
    def _image_set(self, repository):
        payload = b"verified partclone image"
        Path(repository, "stratis.img").write_bytes(payload)
        manifest = ImageManifest.from_dict({
            "schema_version": 1, "image_id": "stratis-image",
            "image_type": "stratis_filesystem", "source_size_bytes": SIZE,
            "logical_sector_size": 512, "partition_table": "none",
            "artifacts": [{
                "filename": "stratis.img", "role": "stratis-filesystem-image",
                "format": "partclone", "compression": "none",
                "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "filesystem": "xfs",
            }],
            "storage": {
                "schema_version": 1, "capture_scope": "stratis_filesystem_bytes",
                "source_layer": "stratis_filesystem",
                "stratis_pool_name": "pool-source", "stratis_pool_uuid": SOURCE_FS_UUID,
                "stratis_filesystem_name": "source", "stratis_filesystem_uuid": SOURCE_FS_UUID,
                "dependencies": [{
                    "kind": "stratis_pool", "identity": SOURCE_FS_UUID,
                    "included_in_source_bytes": False,
                }],
            },
        })
        Path(repository, "stratis-image.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
        return manifest

    def test_restores_to_distinct_precreated_stratis_filesystem(self):
        with tempfile.TemporaryDirectory() as repository:
            manifest = self._image_set(repository)
            run = lambda *args, **kwargs: SimpleNamespace(
                stdout=f"{TARGET_SIZE} dm 512 0", returncode=0, stderr=""
            )
            process = FakeProcess()
            with patch(
                "feclora.storage.stratis_filesystem_restore._verify_partclone_target"
            ) as verify, patch(
                "feclora.storage.stratis_filesystem_restore.stop_process"
            ):
                result = restore_stratis_filesystem_image(
                    "stratis-image.manifest.json", repository, "/dev/dm-9",
                    confirmation="ERASE /dev/dm-9",
                    inventory_provider=lambda: target_inventory(),
                    executables={"lsblk": "/usr/bin/lsblk", "partclone.xfs": "/usr/bin/partclone.xfs",
                                 "xfs_repair": "/usr/sbin/xfs_repair"},
                    runner=run, device_validator=lambda _: True,
                    popen_factory=lambda *args, **kwargs: process,
                    target_safety_check=lambda _: None,
                    effective_uid=lambda: 0,
                )
            self.assertEqual(result, manifest)
            verify.assert_called_once()

    def test_rejects_restoring_over_source_filesystem(self):
        with tempfile.TemporaryDirectory() as repository:
            self._image_set(repository)
            with self.assertRaisesRegex(StratisFilesystemRestoreError, "is the source"):
                restore_stratis_filesystem_image(
                    "stratis-image.manifest.json", repository, "/dev/dm-9",
                    confirmation="ERASE /dev/dm-9",
                    inventory=target_inventory(SOURCE_FS_UUID),
                    executables={"lsblk": "/usr/bin/lsblk", "partclone.xfs": "/usr/bin/partclone.xfs",
                                 "xfs_repair": "/usr/sbin/xfs_repair"},
                    device_validator=lambda _: True,
                )

    def test_rejects_target_pool_with_reported_alerts(self):
        with tempfile.TemporaryDirectory() as repository:
            self._image_set(repository)
            value = target_inventory()
            value["stratis_topology"]["pools"][0]["alerts_reported"] = True
            with self.assertRaisesRegex(StratisFilesystemRestoreError, "reports alerts"):
                restore_stratis_filesystem_image(
                    "stratis-image.manifest.json", repository, "/dev/dm-9",
                    confirmation="ERASE /dev/dm-9", inventory=value,
                    device_validator=lambda _: True,
                )

    def test_rejects_mounted_target(self):
        with tempfile.TemporaryDirectory() as repository:
            self._image_set(repository)
            with self.assertRaisesRegex(StratisFilesystemRestoreError, "is mounted"):
                restore_stratis_filesystem_image(
                    "stratis-image.manifest.json", repository, "/dev/dm-9",
                    confirmation="ERASE /dev/dm-9",
                    inventory=target_inventory(mountpoints=["/mnt/data"]),
                    executables={"lsblk": "/usr/bin/lsblk", "partclone.xfs": "/usr/bin/partclone.xfs",
                                 "xfs_repair": "/usr/sbin/xfs_repair"},
                    device_validator=lambda _: True,
                )

    def test_rejects_insufficient_logical_capacity(self):
        with tempfile.TemporaryDirectory() as repository:
            self._image_set(repository)
            with self.assertRaisesRegex(StratisFilesystemRestoreError, "capacity"):
                restore_stratis_filesystem_image(
                    "stratis-image.manifest.json", repository, "/dev/dm-9",
                    confirmation="ERASE /dev/dm-9",
                    inventory=target_inventory(size=SIZE - 4096),
                    executables={"lsblk": "/usr/bin/lsblk", "partclone.xfs": "/usr/bin/partclone.xfs",
                                 "xfs_repair": "/usr/sbin/xfs_repair"},
                    runner=lambda *args, **kwargs: SimpleNamespace(
                        stdout=f"{SIZE - 4096} dm 512 0", returncode=0, stderr=""
                    ),
                    device_validator=lambda _: True,
                )

    def test_requires_exact_destructive_confirmation(self):
        with tempfile.TemporaryDirectory() as repository:
            self._image_set(repository)
            with self.assertRaisesRegex(StratisFilesystemRestoreError, "confirmation"):
                restore_stratis_filesystem_image(
                    "stratis-image.manifest.json", repository, "/dev/dm-9",
                    confirmation="ERASE /dev/dm-8",
                    inventory=target_inventory(),
                    device_validator=lambda _: True,
                )


if __name__ == "__main__":
    unittest.main()
