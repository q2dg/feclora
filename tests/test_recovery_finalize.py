import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.recovery_finalize import (
    RecoveryFinalizeError,
    finalize_recovery_job,
)


class RecoveryFinalizeTests(unittest.TestCase):
    def _job(self, repository, *, state="completed", map_status="0x0 0x100 +\n",
             partition_table="none"):
        workspace = os.path.join(repository, ".feclora-recovery-rescue")
        os.mkdir(workspace, 0o700)
        image = os.path.join(workspace, "recovered.img")
        with open(image, "wb") as stream:
            stream.write(b"x" * 256)
        os.chmod(image, 0o600)
        mapfile = os.path.join(workspace, "recovery.map")
        with open(mapfile, "w", encoding="ascii") as stream:
            stream.write("# Mapfile. Created by GNU ddrescue\n")
            stream.write("# current_pos current_status current_pass\n0x0 ? 1\n")
            stream.write("# pos size status\n" + map_status)
        os.chmod(mapfile, 0o600)
        metadata = {
            "schema_version": 1, "job_id": "rescue",
            "source_path": "/dev/sda", "source_identity": "wwn:naa.5000c50012345678",
            "source_size_bytes": 256, "logical_sector_size": 512,
            "partition_table": partition_table, "state": state, "retry_passes": 3,
            "mapfile": {
                "rescued_bytes": 256 if state == "completed" else 128,
                "non_tried_bytes": 0, "non_trimmed_bytes": 0,
                "non_scraped_bytes": 0, "bad_sector_bytes": 0 if state == "completed" else 128,
            },
        }
        with open(os.path.join(workspace, "job.json"), "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)
        os.chmod(os.path.join(workspace, "job.json"), 0o600)
        return workspace

    def test_finalizes_only_complete_recovery_as_normal_disk_image(self):
        with tempfile.TemporaryDirectory() as repository:
            self._job(repository)
            manifest = finalize_recovery_job("rescue", repository)
            self.assertEqual(manifest.image_type, "disk")
            self.assertEqual(manifest.partition_table, "none")
            self.assertEqual(manifest.source_size_bytes, 256)
            self.assertEqual(len(manifest.artifacts), 2)
            self.assertTrue(os.path.isfile(os.path.join(repository, "rescue.manifest.json")))
            self.assertTrue(os.path.isfile(os.path.join(repository, "rescue.disk.raw")))

    def test_rejects_degraded_job_even_if_called_to_finalize(self):
        with tempfile.TemporaryDirectory() as repository:
            self._job(repository, state="degraded", map_status="0x0 0x80 +\n0x80 0x80 -\n")
            with self.assertRaisesRegex(RecoveryFinalizeError, "only a completed"):
                finalize_recovery_job("rescue", repository)
            self.assertFalse(os.path.exists(os.path.join(repository, "rescue.manifest.json")))

    def test_rejects_mapfile_with_unreadable_sectors(self):
        with tempfile.TemporaryDirectory() as repository:
            self._job(repository, map_status="0x0 0x80 +\n0x80 0x80 -\n")
            with self.assertRaisesRegex(RecoveryFinalizeError, "unreadable or untried"):
                finalize_recovery_job("rescue", repository)

    def test_rejects_partition_table_type_mismatch(self):
        with tempfile.TemporaryDirectory() as repository:
            self._job(repository, partition_table="gpt")
            runner = lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0, stdout="label: dos\nunit: sectors\n", stderr=""
            )
            with self.assertRaisesRegex(RecoveryFinalizeError, "does not match"):
                finalize_recovery_job(
                    "rescue", repository, executables={"sfdisk": "/usr/bin/sfdisk"},
                    runner=runner,
                )

    def test_refuses_to_overwrite_existing_image_set(self):
        with tempfile.TemporaryDirectory() as repository:
            self._job(repository)
            finalize_recovery_job("rescue", repository)
            with self.assertRaises(RecoveryFinalizeError):
                finalize_recovery_job("rescue", repository)


if __name__ == "__main__":
    unittest.main()
