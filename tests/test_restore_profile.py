import json
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
    load_restore_profile,\n    save_unattended_restore_profile,
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

    def test_unattended_profile_requires_signature_and_is_target_bound(self):
        value = profile_data(
            execution_mode="unattended",
            expires_at="2030-01-01T00:00:00Z",
            single_use=True,
        )
        with self.assertRaisesRegex(RestoreProfileError, "not been verified"):
            RestoreProfile.from_dict(value).authorize(
                {"wwn": value["target"]["wwn"], "serial": value["target"]["serial"]},
                now=datetime(2029, 1, 1, tzinfo=timezone.utc),
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restore.json"
            key = Path(directory) / "trusted.pub"
            signature = Path(str(path) + ".minisig")
            path.write_text(json.dumps(value), encoding="utf-8")
            key.write_text("trusted key", encoding="utf-8")
            signature.write_text("signature", encoding="utf-8")
            with patch("feclora.storage.restore_profile.subprocess.run") as run:
                profile = load_restore_profile(
                    path, minisign_public_key=key, minisign_executable="/usr/bin/minisign",
                )
            run.assert_called_once()
            profile.authorize(
                {"wwn": value["target"]["wwn"], "serial": value["target"]["serial"]},
                now=datetime(2029, 1, 1, tzinfo=timezone.utc),
            )
            with self.assertRaisesRegex(RestoreProfileError, "already been consumed"):
                profile.authorize(
                    {"wwn": value["target"]["wwn"], "serial": value["target"]["serial"]},
                    now=datetime(2029, 1, 1, tzinfo=timezone.utc),
                    already_consumed=True,
                )

    def test_save_creates_signed_profile_without_overwriting(self):
        profile = RestoreProfile.from_dict(profile_data(
            execution_mode="unattended",
            expires_at="2030-01-01T00:00:00Z",
            single_use=True,
        ))
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "secret.key"
            key.write_text("secret", encoding="utf-8")
            key.chmod(0o600)
            destination = Path(directory) / "profile.json"
            def sign(command, **kwargs):
                Path(str(destination) + ".minisig").write_text("signature", encoding="utf-8")
            with patch("feclora.storage.restore_profile.shutil.which", return_value="/usr/bin/minisign"), \\
                 patch("feclora.storage.restore_profile.subprocess.run", side_effect=sign):
                saved = save_unattended_restore_profile(
                    profile, destination, minisign_secret_key=key,
                )
            self.assertEqual(saved, destination)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertTrue(Path(str(destination) + ".minisig").is_file())
            with self.assertRaisesRegex(RestoreProfileError, "overwrite"):
                save_unattended_restore_profile(
                    profile, destination, minisign_secret_key=key,
                    minisign_executable="/usr/bin/minisign",
                )

    def test_save_rejects_permissive_minisign_secret_key(self):
        profile = RestoreProfile.from_dict(profile_data(
            execution_mode="unattended",
            expires_at="2030-01-01T00:00:00Z",
            single_use=True,
        ))
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "secret.key"
            key.write_text("secret", encoding="utf-8")
            key.chmod(0o644)
            with self.assertRaisesRegex(RestoreProfileError, "mode 0600"):
                save_unattended_restore_profile(
                    profile, Path(directory) / "profile.json",
                    minisign_secret_key=key, minisign_executable="/usr/bin/minisign",
                )

    def test_rejects_expired_unattended_profile(self):
        value = profile_data(
            execution_mode="unattended",
            expires_at="2028-01-01T00:00:00Z",
            single_use=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restore.json"
            key = Path(directory) / "trusted.pub"
            Path(str(path) + ".minisig").write_text("signature", encoding="utf-8")
            path.write_text(json.dumps(value), encoding="utf-8")
            key.write_text("trusted key", encoding="utf-8")
            with patch("feclora.storage.restore_profile.subprocess.run"):
                profile = load_restore_profile(
                    path, minisign_public_key=key, minisign_executable="/usr/bin/minisign",
                )
            with self.assertRaisesRegex(RestoreProfileError, "expired"):
                profile.authorize(
                    {"wwn": profile.target.wwn, "serial": profile.target.serial},
                    now=datetime(2029, 1, 1, tzinfo=timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
