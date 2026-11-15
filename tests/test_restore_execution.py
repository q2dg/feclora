from __future__ import annotations

import unittest
from unittest.mock import patch

from feclora.deployment.restore_execution import (
    RestoreExecutionError,
    execute_restore,
)


class SharedRestoreExecutionTests(unittest.TestCase):
    def test_disk_restore_receives_passphrase_and_prewrite_identity_check(self):
        pre_write = lambda: None
        with patch("feclora.deployment.restore_execution.restore_disk") as restore:
            execute_restore(
                "/repo/image.manifest.json", "/repo", "/dev/sda",
                target_type="disk", confirmation="ERASE /dev/sda",
                age_passphrase="one-shot-secret",
                pre_write_callback=pre_write,
            )
        restore.assert_called_once()
        self.assertEqual(restore.call_args.args, (
            "/repo/image.manifest.json", "/repo", "/dev/sda",
        ))
        self.assertEqual(restore.call_args.kwargs["age_passphrase"], "one-shot-secret")
        self.assertIs(restore.call_args.kwargs["pre_write_callback"], pre_write)

    def test_partition_and_logical_volume_use_their_existing_restore_engines(self):
        with patch("feclora.deployment.restore_execution.restore_partition") as partition, \
             patch("feclora.deployment.restore_execution.restore_logical_volume") as logical:
            execute_restore(
                "/repo/part.manifest.json", "/repo", "/dev/sda2",
                target_type="partition", confirmation="ERASE /dev/sda2",
                age_identity_file="/keys/client.age",
            )
            execute_restore(
                "/repo/lv.manifest.json", "/repo", "/dev/vg0/root",
                target_type="logical_volume", confirmation="ERASE /dev/vg0/root",
            )
        partition.assert_called_once()
        self.assertEqual(partition.call_args.kwargs["age_identity_file"], "/keys/client.age")
        logical.assert_called_once()
        self.assertTrue(callable(logical.call_args.kwargs["inventory_provider"]))

    def test_wrong_confirmation_and_conflicting_age_sources_fail_before_io(self):
        with patch("feclora.deployment.restore_execution.restore_disk") as restore:
            with self.assertRaisesRegex(RestoreExecutionError, "explicit local restore confirmation"):
                execute_restore(
                    "/repo/image.manifest.json", "/repo", "/dev/sda",
                    target_type="disk", confirmation="ERASE /dev/sdb",
                )
            with self.assertRaisesRegex(RestoreExecutionError, "either an age identity"):
                execute_restore(
                    "/repo/image.manifest.json", "/repo", "/dev/sda",
                    target_type="disk", confirmation="ERASE /dev/sda",
                    age_identity_file="/keys/client.age", age_passphrase="secret",
                )
        restore.assert_not_called()


if __name__ == "__main__":
    unittest.main()
