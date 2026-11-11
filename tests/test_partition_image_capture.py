import hashlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from feclora.storage.image_manifest import ImageArtifact
from feclora.storage.partition_image_capture import PartitionImageCaptureError, capture_partition_image


class FakeProcess:
    def __init__(self, data):
        self.stdout = io.BytesIO(data)
        self.returncode = 0
    def poll(self):
        return self.returncode
    def wait(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15



def make_inventory(source_path, size, filesystem):
    return {
        "devices": [{
            "path": source_path, "type": "part", "size_bytes": size,
            "logical_sector_size": 512, "filesystem": filesystem,
            "major_minor": "8:1", "children": [],
        }],
        "storage_graph": {"status": "available", "nodes": [], "edges": []},
        "luks_metadata": {"status": "available", "containers": []},
        "btrfs_topology": {"filesystems": []},
    }


class PartitionImageCaptureTests(unittest.TestCase):
    def test_rejects_path_traversal_image_and_partition_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            for image_id, partition_id in (("../escape", "root"), ("safe", "../escape")):
                with self.subTest(image_id=image_id, partition_id=partition_id):
                    with self.assertRaisesRegex(PartitionImageCaptureError, "filename-compatible"):
                        capture_partition_image(
                            "/dev/fake1", image_id, partition_id, directory,
                            executables={"lsblk": "lsblk", "dd": "dd"},
                            device_validator=lambda _path: True,
                            source_safety_check=lambda _path: None,
                            effective_uid=lambda: 0,
                            inventory=make_inventory("/dev/fake1", 4096, "unknown"),
                        )
            self.assertEqual(os.listdir(directory), [])

    def test_publishes_raw_partition_and_manifest(self):
        payload = b"x" * 4096
        with tempfile.TemporaryDirectory() as directory:
            def runner(command, **kwargs):
                return SimpleNamespace(stdout=f"{len(payload)} 512 part unknown\n")
            manifest = capture_partition_image(
                "/dev/fake1", "backup-part", "fake1", directory,
                executables={"lsblk": "lsblk", "dd": "dd"},
                runner=runner, device_validator=lambda _path: True,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: FakeProcess(payload),
                inventory=make_inventory("/dev/fake1", len(payload), "unknown"),
            )
            self.assertEqual(manifest.image_type, "partition")
            self.assertEqual(manifest.source_size_bytes, len(payload))
            self.assertEqual(manifest.artifacts[0].format, "raw")
            self.assertEqual(
                set(os.listdir(directory)),
                {"backup-part_fake1.img", "backup-part.manifest.json"},
            )

    def test_luks2_partition_image_records_encrypted_container_provenance(self):
        payload = b"x" * 4096
        storage = {
            "schema_version": 1,
            "capture_scope": "encrypted_container_bytes",
            "source_layer": "luks2_container",
            "luks_uuid": "12345678-1234-1234-1234-123456789abc",
            "dependencies": [{
                "kind": "luks2_metadata",
                "identity": "12345678-1234-1234-1234-123456789abc",
                "included_in_source_bytes": True,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            def runner(command, **kwargs):
                return SimpleNamespace(stdout=f"{len(payload)} 512 part crypto_LUKS\n")
            with patch(
                "feclora.storage.partition_image_capture.plan_storage_capture",
                return_value={"blockers": [], "manifest_storage": storage},
            ):
                manifest = capture_partition_image(
                    "/dev/fake1", "luks-backup", "luks", directory,
                    executables={"lsblk": "lsblk", "dd": "dd"},
                    runner=runner, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                    popen_factory=lambda *a, **k: FakeProcess(payload),
                    inventory=make_inventory("/dev/fake1", len(payload), "crypto_LUKS"),
                )
            self.assertEqual(manifest.storage["source_layer"], "luks2_container")
            self.assertEqual(manifest.storage["capture_scope"], "encrypted_container_bytes")
            self.assertEqual(manifest.storage["luks_uuid"], storage["luks_uuid"])

    def test_single_device_btrfs_capture_uses_partclone_and_records_uuid(self):
        payload = b"btrfs partclone stream"
        btrfs_show = """Label: none  uuid: 01234567-89ab-cdef-0123-456789abcdef
        Total devices 1 FS bytes used 123456
        devid    1 size 4096 path /dev/fake1
"""
        with tempfile.TemporaryDirectory() as directory:
            def runner(command, **kwargs):
                if command[0] == "lsblk":
                    return SimpleNamespace(stdout="4096 512 part btrfs\\n")
                return SimpleNamespace(stdout=btrfs_show, returncode=0)
            inventory = make_inventory("/dev/fake1", 4096, "btrfs")
            inventory["btrfs_topology"] = {"status": "available", "filesystems": [{
                "uuid": "01234567-89ab-cdef-0123-456789abcdef",
                "total_devices": 1, "devices": [{"path": "/dev/fake1"}],
            }]}
            manifest = capture_partition_image(
                "/dev/fake1", "btrfs-backup", "fake1", directory,
                executables={
                    "lsblk": "lsblk", "btrfs": "btrfs",
                    "partclone.btrfs": "partclone.btrfs",
                },
                runner=runner, device_validator=lambda _path: True,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: FakeProcess(payload),
                inventory=inventory,
            )
            self.assertEqual(manifest.artifacts[0].format, "partclone")
            self.assertEqual(manifest.artifacts[0].filesystem, "btrfs")
            self.assertEqual(manifest.storage["source_layer"], "btrfs_filesystem")
            self.assertEqual(manifest.storage["btrfs_uuid"], "01234567-89ab-cdef-0123-456789abcdef")

    def test_rejects_multi_device_btrfs_capture_before_writing(self):
        payload = """Label: array uuid: 01234567-89ab-cdef-0123-456789abcdef
        Total devices 2 FS bytes used 123456
        devid    1 size 1000000 path /dev/fake1
        devid    2 size 2000000 path /dev/fake2
"""
        with tempfile.TemporaryDirectory() as directory:
            def runner(command, **kwargs):
                if command[0] == "lsblk":
                    return SimpleNamespace(stdout="4096 512 part btrfs\n")
                return SimpleNamespace(stdout=payload, returncode=0)
            with self.assertRaisesRegex(PartitionImageCaptureError, "multi-device Btrfs"):
                capture_partition_image(
                    "/dev/fake1", "btrfs-backup", "fake1", directory,
                    executables={"lsblk": "lsblk", "btrfs": "btrfs", "dd": "dd"},
                    runner=runner, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                    popen_factory=lambda *a, **k: FakeProcess(b"unused"),
                    inventory=make_inventory("/dev/fake1", 4096, "btrfs"),
                )
            self.assertEqual(os.listdir(directory), [])

    def test_raw_short_read_does_not_publish_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            def runner(command, **kwargs):
                return SimpleNamespace(stdout="4096 512 part unknown\n")
            with self.assertRaisesRegex(PartitionImageCaptureError, "size mismatch"):
                capture_partition_image(
                    "/dev/fake1", "short", "fake1", directory,
                    executables={"lsblk": "lsblk", "dd": "dd"},
                    runner=runner, device_validator=lambda _path: True,
                    source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                    popen_factory=lambda *a, **k: FakeProcess(b"short"),
                    inventory=make_inventory("/dev/fake1", 4096, "unknown"),
                )
            self.assertEqual(os.listdir(directory), [])

    def test_partclone_capture_records_filesystem(self):
        payload = b"partclone container"
        with tempfile.TemporaryDirectory() as directory:
            def runner(command, **kwargs):
                return SimpleNamespace(stdout="8192 512 part ext4\n")
            manifest = capture_partition_image(
                "/dev/fake1", "ext4-backup", "fake1", directory,
                executables={"lsblk": "lsblk", "partclone.ext4": "partclone.ext4", "dd": "dd"},
                runner=runner, device_validator=lambda _path: True,
                source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                popen_factory=lambda *a, **k: FakeProcess(payload),
                inventory=make_inventory("/dev/fake1", 8192, "ext4"),
            )
            self.assertEqual(manifest.artifacts[0].format, "partclone")
            self.assertEqual(manifest.artifacts[0].filesystem, "ext4")


    def test_zstd_and_lz4_use_supported_partition_suffixes(self):
        for codec, suffix in (("zstd", ".zst"), ("lz4", ".lz4")):
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as directory:
                def runner(command, **kwargs):
                    return SimpleNamespace(stdout="4096 512 part unknown\n")

                def fake_capture(source, filesystem, stage, filename, partition_id,
                                 executables, **kwargs):
                    stored = b"compressed partition payload"
                    with open(os.path.join(stage, filename), "wb") as output:
                        output.write(stored)
                    return ImageArtifact(
                        filename=filename, role="partition-image", format="raw",
                        compression=codec, size_bytes=len(stored),
                        sha256=hashlib.sha256(stored).hexdigest(),
                        partition_id=partition_id, compression_level=3,
                    )

                with patch("feclora.storage.partition_image_capture.capture_partition",
                           side_effect=fake_capture):
                    manifest = capture_partition_image(
                        "/dev/fake1", "codec-part", "fake1", directory,
                        compression=codec, compression_level=3,
                        executables={"lsblk": "lsblk", "dd": "dd"},
                        runner=runner, device_validator=lambda _path: True,
                        source_safety_check=lambda _path: None, effective_uid=lambda: 0,
                        inventory=make_inventory("/dev/fake1", 4096, "unknown"),
                    )
                self.assertTrue(os.path.isfile(os.path.join(directory, "codec-part_fake1.img" + suffix)))
                self.assertEqual(manifest.artifacts[0].compression, codec)


if __name__ == "__main__":
    unittest.main()
