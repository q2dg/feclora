import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from feclora.storage.profile_executor import _consume_profile_once, _matching_target, _require_persistent_ledger, main
from feclora.storage.restore_profile import RestoreProfileError


class ProfileConsumptionLedgerTests(unittest.TestCase):
    def test_target_matching_requires_exactly_one_stable_disk_identity(self):
        from feclora.storage.restore_profile import RestoreProfile
        import uuid
        profile = RestoreProfile.from_dict({
            "schema_version": 1,
            "profile_id": str(uuid.UUID("12f7b67b-44e0-4d0b-a0b2-58b3d02c04e7")),
            "name": "Lab restore",
            "image_manifest": "image.manifest.json",
            "target": {"wwn": "wwn-1", "serial": "serial-1"},
            "execution_mode": "interactive",
            "layout_policy": "preserve",
            "verify_after_restore": True,
            "on_success": "none",
            "expires_at": None,
            "single_use": False,
        })
        inventory = {"devices": [
            {"type": "disk", "path": "/dev/sda", "wwn": "wwn-1", "serial": "serial-1"},
            {"type": "part", "path": "/dev/sda1", "wwn": "wwn-1", "serial": "serial-1"},
        ]}
        self.assertEqual(_matching_target(profile, inventory)["path"], "/dev/sda")
        inventory["devices"].append(
            {"type": "disk", "path": "/dev/sdb", "wwn": "wwn-1", "serial": "serial-1"}
        )
        with self.assertRaisesRegex(RestoreProfileError, "exactly one"):
            _matching_target(profile, inventory)

    def test_persistent_ledger_accepts_dedicated_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "audit").mkdir()
            with patch("feclora.storage.profile_executor.shutil.which", return_value="/usr/bin/findmnt"):
                _require_persistent_ledger(
                    Path(directory) / "audit" / "consumed.jsonl",
                    runner=lambda *args, **kwargs: type("Result", (), {"stdout": "ext4 /mnt/restore-media\\n"})(),
                )

    def test_persistent_ledger_rejects_live_overlay_and_root(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "audit").mkdir()
            with patch("feclora.storage.profile_executor.shutil.which", return_value="/usr/bin/findmnt"):
                for output in ("overlay /run/initramfs/live\n", "ext4 /\n"):
                    with self.assertRaisesRegex(RestoreProfileError, "dedicated persistent"):
                        _require_persistent_ledger(
                            Path(directory) / "audit" / "consumed.jsonl",
                            runner=lambda *args, _output=output, **kwargs: type("Result", (), {"stdout": _output})(),
                        )

    def test_consumption_is_durable_and_replay_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "logs" / "consumed.jsonl"
            _consume_profile_once("profile-123", ledger)
            event = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(event, {"profile_id": "profile-123", "status": "consumed"})
            with self.assertRaisesRegex(RestoreProfileError, "already been consumed"):
                _consume_profile_once("profile-123", ledger)

    def test_corrupt_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "consumed.jsonl"
            ledger.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(RestoreProfileError, "corrupt"):
                _consume_profile_once("profile-456", ledger)

    def test_symlink_ledger_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real.jsonl"
            link = Path(directory) / "ledger.jsonl"
            real.write_text("", encoding="utf-8")
            link.symlink_to(real)
            with self.assertRaises(RestoreProfileError):
                _consume_profile_once("profile-789", link)



class ProfileExecutorCliTests(unittest.TestCase):
    def test_environment_file_values_are_used_as_cli_defaults(self):
        environment = {
            "FECLORA_PROFILE": "/profiles/restore.json",
            "FECLORA_IMAGE_REPOSITORY": "/mnt/images",
            "FECLORA_CONSUMPTION_LEDGER": "/mnt/audit/consumed.jsonl",
            "FECLORA_OPERATION_LOG": "/mnt/audit/operations.jsonl",
            "FECLORA_AGE_IDENTITY": "/etc/feclora/identity.txt",
        }
        manifest = type("Manifest", (), {"image_id": "image-1"})()
        with patch.dict(os.environ, environment, clear=True), patch(
            "feclora.storage.profile_executor.execute_unattended_restore_profile",
            return_value=manifest,
        ) as execute:
            self.assertEqual(main([]), 0)
        execute.assert_called_once_with(
            "/profiles/restore.json",
            consumption_ledger="/mnt/audit/consumed.jsonl",
            operation_log_path="/mnt/audit/operations.jsonl",
            repository="/mnt/images",
            age_identity_file="/etc/feclora/identity.txt",
        )

    def test_explicit_cli_arguments_override_environment_defaults(self):
        environment = {
            "FECLORA_PROFILE": "/profiles/from-env.json",
            "FECLORA_CONSUMPTION_LEDGER": "/mnt/audit/from-env.jsonl",
            "FECLORA_OPERATION_LOG": "/mnt/audit/from-env-ops.jsonl",
        }
        manifest = type("Manifest", (), {"image_id": "image-2"})()
        with patch.dict(os.environ, environment, clear=True), patch(
            "feclora.storage.profile_executor.execute_unattended_restore_profile",
            return_value=manifest,
        ) as execute:
            self.assertEqual(main([
                "--profile", "/profiles/explicit.json",
                "--consumption-ledger", "/mnt/audit/explicit.jsonl",
                "--operation-log", "/mnt/audit/explicit-ops.jsonl",
            ]), 0)
        execute.assert_called_once_with(
            "/profiles/explicit.json",
            consumption_ledger="/mnt/audit/explicit.jsonl",
            operation_log_path="/mnt/audit/explicit-ops.jsonl",
            repository="/home/feclora/images",
            age_identity_file=None,
        )

if __name__ == "__main__":
    unittest.main()
