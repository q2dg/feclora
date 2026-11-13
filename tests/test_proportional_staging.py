import gzip
import binascii
import struct
import uuid
import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from feclora.storage.image_manifest import ImageManifest
from feclora.storage.proportional_staging import (
    ProportionalStagingError,
    stage_verified_raw_disk_image,
    StagedRawDiskImage,
    apply_gpt_rewrite_to_staged_image,
)


class VerifiedProportionalStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repository = os.path.join(self.temp.name, "repository")
        self.staging_root = os.path.join(self.temp.name, "local-stage")
        os.mkdir(self.repository)
        os.mkdir(self.staging_root)
        self.payload = (b"verified whole disk payload\x00" * 128)
        self.stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.repository, "disk.raw.gz"), "wb") as stream:
            stream.write(self.stored)
        with open(os.path.join(self.repository, "table.sfdisk"), "wb") as stream:
            stream.write(b"x")
        self.manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": "stage-test",
            "image_type": "disk",
            "source_size_bytes": len(self.payload),
            "logical_sector_size": 512,
            "partition_table": "gpt",
            "artifacts": [
                {"filename": "disk.raw.gz", "role": "disk-image", "format": "raw",
                 "compression": "gzip", "size_bytes": len(self.stored),
                 "sha256": hashlib.sha256(self.stored).hexdigest()},
                {"filename": "table.sfdisk", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": 1,
                 "sha256": hashlib.sha256(b"x").hexdigest()},
            ],
        })

    def test_creates_private_decoded_copy_and_removes_it_on_context_exit(self):
        original = Path(self.repository, "disk.raw.gz").read_bytes()
        with stage_verified_raw_disk_image(
            self.manifest, self.repository, staging_root=self.staging_root
        ) as staged:
            self.assertEqual(staged.size_bytes, len(self.payload))
            self.assertEqual(staged.sha256, hashlib.sha256(self.payload).hexdigest())
            self.assertEqual(Path(staged.path).read_bytes(), self.payload)
            self.assertEqual(os.stat(staged.path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(staged.path)).st_mode & 0o777, 0o700)
            self.assertEqual(os.listdir(self.staging_root), [os.path.basename(os.path.dirname(staged.path))])
        self.assertEqual(os.listdir(self.staging_root), [])
        self.assertEqual(Path(self.repository, "disk.raw.gz").read_bytes(), original)

    def test_rejects_staging_inside_the_source_repository(self):
        with self.assertRaisesRegex(ProportionalStagingError, "outside the image repository"):
            with stage_verified_raw_disk_image(
                self.manifest, self.repository, staging_root=self.repository
            ):
                self.fail("staging must not begin inside the repository")

    def test_rejects_tampered_source_before_yield_and_cleans_stage(self):
        with open(os.path.join(self.repository, "disk.raw.gz"), "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(ProportionalStagingError):
            with stage_verified_raw_disk_image(
                self.manifest, self.repository, staging_root=self.staging_root
            ):
                self.fail("tampered source must never be yielded")
        self.assertEqual(os.listdir(self.staging_root), [])

    def test_rejects_non_disk_manifest(self):
        partition_manifest = ImageManifest.from_dict({
            "schema_version": 1,
            "image_id": "partition-test",
            "image_type": "partition",
            "source_size_bytes": len(self.payload),
            "logical_sector_size": 512,
            "partition_table": "none",
            "artifacts": [
                {"filename": "disk.raw.gz", "role": "partition-image", "format": "raw",
                 "compression": "gzip", "size_bytes": len(self.stored),
                 "sha256": hashlib.sha256(self.stored).hexdigest(), "partition_id": "p1"}
            ],
        })
        with self.assertRaisesRegex(ProportionalStagingError, "whole-disk"):
            with stage_verified_raw_disk_image(
                partition_manifest, self.repository, staging_root=self.staging_root
            ):
                self.fail("partition image must not be staged as a whole disk")


    def _synthetic_gpt(self):
        sector_size = 512
        disk_sectors = 100
        entry_count = 128
        entry_size = 128
        array = bytearray(entry_count * entry_size)
        type_guid = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")
        unique_guid = uuid.UUID("11111111-2222-3333-4444-555555555555")
        first_usable = 34
        last_usable = disk_sectors - 34
        struct.pack_into("<16s16sQQQ", array, 0, type_guid.bytes_le,
                         unique_guid.bytes_le, 35, 44, 0)
        array[56:64] = "root".encode("utf-16le")
        array_crc = binascii.crc32(array) & 0xffffffff
        disk_guid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        image = bytearray(sector_size * disk_sectors)
        image[510:512] = b"\\x55\\xaa"
        image[450] = 0xee
        struct.pack_into("<II", image, 454, 1, disk_sectors - 1)
        array_sectors = len(array) // sector_size

        def header(current, backup, entries):
            raw = bytearray(sector_size)
            struct.pack_into("<8sIIIIQQQQ16sQIII", raw, 0, b"EFI PART",
                             0x10000, 92, 0, 0, current, backup, first_usable,
                             last_usable, disk_guid.bytes_le, entries,
                             entry_count, entry_size, array_crc)
            struct.pack_into("<I", raw, 16, binascii.crc32(raw[:92]) & 0xffffffff)
            return raw

        backup_entries = disk_sectors - 1 - array_sectors
        image[2 * sector_size:2 * sector_size + len(array)] = array
        image[backup_entries * sector_size:backup_entries * sector_size + len(array)] = array
        image[sector_size:2 * sector_size] = header(1, disk_sectors - 1, 2)
        image[(disk_sectors - 1) * sector_size:] = header(
            disk_sectors - 1, 1, backup_entries
        )
        return bytes(image)

    def test_applies_gpt_only_to_private_regular_staging_file_and_verifies(self):
        workspace = os.path.join(self.staging_root, "private")
        os.mkdir(workspace, 0o700)
        os.chmod(workspace, 0o700)
        path = os.path.join(workspace, "disk.raw")
        original = self._synthetic_gpt()
        with open(path, "xb") as stream:
            stream.write(original)
        os.chmod(path, 0o600)
        staged = StagedRawDiskImage(
            path, len(original), hashlib.sha256(original).hexdigest()
        )
        plan = SimpleNamespace(
            node="/dev/loop0p1",
            partuuid="11111111-2222-3333-4444-555555555555",
            type_guid="0fc63daf-8483-4772-8e79-3d69d8477de4",
            start_sector=35,
            size_sectors=8,
        )
        result = apply_gpt_rewrite_to_staged_image(
            staged, target_size_bytes=90 * 512, sector_size=512,
            planned_partitions=(plan,),
        )
        self.assertEqual(result.size_bytes, 90 * 512)
        self.assertEqual(os.path.getsize(path), 90 * 512)
        self.assertNotEqual(Path(path).read_bytes(), original[:90 * 512])
        from feclora.storage.gpt_binary import inspect_gpt_binary
        with open(path, "rb") as stream:
            metadata = inspect_gpt_binary(
                stream, sector_size=512, disk_size_bytes=90 * 512
            )
        self.assertTrue(metadata["primary_backup_consistent"])
        self.assertEqual(metadata["partitions"][0]["last_lba"], 42)
        self.assertEqual(result.sha256, hashlib.sha256(Path(path).read_bytes()).hexdigest())

    def test_rejects_staged_file_digest_mismatch_before_mutation(self):
        workspace = os.path.join(self.staging_root, "private-digest")
        os.mkdir(workspace, 0o700)
        os.chmod(workspace, 0o700)
        path = os.path.join(workspace, "disk.raw")
        payload = b"not a disk"
        Path(path).write_bytes(payload)
        os.chmod(path, 0o600)
        staged = StagedRawDiskImage(path, len(payload), "0" * 64)
        with self.assertRaisesRegex(ProportionalStagingError, "digest changed"):
            apply_gpt_rewrite_to_staged_image(
                staged, target_size_bytes=512, sector_size=512,
                planned_partitions=(),
            )
        self.assertEqual(Path(path).read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
