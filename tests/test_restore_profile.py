import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from feclora.storage.restore_profile import (
    RestoreProfile,
    RestoreProfileError,
    RestoreTargetSelector,
    load_restore_profile,
    save_unattended_restore_profile,
)


def profile_data(**changes):
    value = {
        "schema_version": 1,
        "profile_id": str(uuid.UUID("12f7b67b-44e0-4d0b-a0b2-58b3d02c04e7")),
        "name": "Lab restore",
        "image_manifest": "golden-image.json",
        "target": {"wwn": "0x5000c50012345678", "serial": "SN-001"},
        "execution_mode": "interactive",
        "layout_policy": "preserve",
        "verify_after_restore": True,
        "on_success": "none",
        "expires_at": None,
        "single_use": False,
    }
    value.update(changes)
    return value


class RestoreProfileTests(unittest.TestCase):
    def test_round_trip_and_stable_target_match(self):
        profile = RestoreProfile.from_dict(profile_data())
        restored = RestoreProfile.from_json(profile.to_json())
        self.assertEqual(restored, profile)
        self.assertTrue(profile.target.matches({"wwn": "0x5000C50012345678", "serial": "SN-001"}))
        self.assertFalse(profile.target.matches({"wwn": "0x5000c50012345678", "serial": "SN-OTHER"}))
        self.assertFalse(profile.target.matches({"name": "/dev/sda"}))

    def test_rejects_device_path_as_image_manifest(self):
        value = profile_data(image_manifest="../other/image.json")
        with self.assertRaisesRegex(RestoreProfileError, "JSON filename"):
            RestoreProfile.from_dict(value)

    def test_rejects_target_without_stable_identifier(self):
        value = profile_data(target={"wwn": None, "serial": None})
        with self.assertRaisesRegex(RestoreProfileError, "requires a WWN"):
            RestoreProfile.from_dict(value)

    def test_rejects_profiles_that_disable_post_write_verification(self):
        with self.assertRaisesRegex(RestoreProfileError, "must require post-write verification"):
            RestoreProfile.from_dict(profile_data(verify_after_restore=False))

    def test_unattended_requires_expiry_and_single_use(self):
        with self.assertRaisesRegex(RestoreProfileError, "require an expiry"):
            RestoreProfile.from_dict(profile_data(execution_mode="unattended"))
        with self.assertRaisesRegex(RestoreProfileError, "single-use"):
            RestoreProfile.from_dict(profile_data(
                execution_mode="unattended", expires_at="2030-01-01T00:00:00Z",
                single_use=False,
            ))

    def test_unattended_profile_requires_root_owned_authorization_and_is_target_bound(self):
        import stat
        from types import SimpleNamespace
        value = profile_data(
            execution_mode="unattended", expires_at="2030-01-01T00:00:00Z", single_use=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restore.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            regular = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=path.stat().st_size)
            folder = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
            def fake_lstat(candidate):
                return regular if os.fspath(candidate) == os.fspath(path) else folder
            with patch("feclora.storage.restore_profile.os.lstat", side_effect=fake_lstat), \
                 patch("feclora.storage.restore_profile.os.fstat", return_value=regular):
                profile = load_restore_profile(path)
            profile.authorize(
                {"wwn": value["target"]["wwn"], "serial": value["target"]["serial"]},
                now=datetime(2029, 1, 1, tzinfo=timezone.utc),
            )
            with self.assertRaisesRegex(RestoreProfileError, "already been consumed"):
                profile.authorize(
                    {"wwn": value["target"]["wwn"], "serial": value["target"]["serial"]},
                    now=datetime(2029, 1, 1, tzinfo=timezone.utc), already_consumed=True,
                )

    def test_save_creates_root_owned_mode_0600_profile_without_sidecar(self):
        import stat
        from types import SimpleNamespace
        profile = RestoreProfile.from_dict(profile_data(
            execution_mode="unattended", expires_at="2030-01-01T00:00:00Z", single_use=True,
        ))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "profile.json"
            folder = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
            with patch("feclora.storage.restore_profile.os.geteuid", return_value=0), \
                 patch("feclora.storage.restore_profile.os.lstat", return_value=folder):
                saved = save_unattended_restore_profile(profile, destination)
                self.assertEqual(saved, destination)
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
                self.assertFalse(Path(str(destination) + ".minisig").exists())
                with self.assertRaisesRegex(RestoreProfileError, "overwrite"):
                    save_unattended_restore_profile(profile, destination)

    def test_save_requires_root_and_protected_parent_directory(self):
        profile = RestoreProfile.from_dict(profile_data(
            execution_mode="unattended", expires_at="2030-01-01T00:00:00Z", single_use=True,
        ))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "profile.json"
            with patch("feclora.storage.restore_profile.os.geteuid", return_value=1000):
                with self.assertRaisesRegex(RestoreProfileError, "created by root"):
                    save_unattended_restore_profile(profile, destination)

    def test_rejects_expired_unattended_profile(self):
        import stat
        from types import SimpleNamespace
        value = profile_data(
            execution_mode="unattended", expires_at="2028-01-01T00:00:00Z", single_use=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restore.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            regular = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=path.stat().st_size)
            folder = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
            def fake_lstat(candidate):
                return regular if os.fspath(candidate) == os.fspath(path) else folder
            with patch("feclora.storage.restore_profile.os.lstat", side_effect=fake_lstat), \
                 patch("feclora.storage.restore_profile.os.fstat", return_value=regular):
                profile = load_restore_profile(path)
            with self.assertRaisesRegex(RestoreProfileError, "expired"):
                profile.authorize(
                    {"wwn": profile.target.wwn, "serial": profile.target.serial},
                    now=datetime(2029, 1, 1, tzinfo=timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
