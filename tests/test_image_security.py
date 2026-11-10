import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from feclora.storage.image_manifest import ImageArtifact
from feclora.storage.image_security import (
    ImageSecurityError, decrypt_artifact_to_temp, encrypt_artifact,
    sign_manifest, verify_manifest_signature, preflight_image_security,
)


class ImageSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.source = os.path.join(self.root, "disk.raw.gz")
        self.recipients = os.path.join(self.root, "recipients.txt")
        self.identity = os.path.join(self.root, "identity.txt")
        self.manifest = os.path.join(self.root, "image.manifest.json")
        self.secret = os.path.join(self.root, "minisign.key")
        self.public = os.path.join(self.root, "minisign.pub")
        for path, data in (
            (self.source, b"compressed bytes"),
            (self.recipients, b"age1example\n"),
            (self.identity, b"AGE-SECRET-KEY-1EXAMPLE\n"),
            (self.manifest, b'{"schema_version":1}\n'),
            (self.secret, b"untrusted test key placeholder"),
            (self.public, b"untrusted test public placeholder"),
        ):
            with open(path, "wb") as stream:
                stream.write(data)
        self.artifact = ImageArtifact(
            filename="disk.raw.gz", role="disk-image", format="raw",
            compression="gzip", size_bytes=len(b"compressed bytes"),
            sha256="0" * 64,
        )

    def test_encrypts_compressed_artifact_and_updates_stored_digest(self):
        def fake_run(command, **kwargs):
            output = command[command.index("--output") + 1]
            with open(output, "wb") as stream:
                stream.write(b"age ciphertext")
            return SimpleNamespace(returncode=0, stderr="")
        with patch("feclora.storage.image_security.subprocess.run", side_effect=fake_run):
            encrypted = encrypt_artifact(
                self.source, self.artifact, self.recipients, age_executable="/usr/bin/age"
            )
        self.assertEqual(encrypted.encryption, "age")
        self.assertEqual(encrypted.filename, "disk.raw.gz.age")
        self.assertEqual(encrypted.size_bytes, len(b"age ciphertext"))
        self.assertFalse(os.path.exists(self.source))
        self.assertTrue(os.path.isfile(os.path.join(self.root, encrypted.filename)))

    def test_encrypt_failure_preserves_plaintext_stage(self):
        with patch("feclora.storage.image_security.subprocess.run",
                   return_value=SimpleNamespace(returncode=1, stderr="bad recipient")):
            with self.assertRaises(ImageSecurityError):
                encrypt_artifact(self.source, self.artifact, self.recipients, age_executable="/usr/bin/age")
        self.assertTrue(os.path.exists(self.source))

    def test_decrypts_to_private_temporary_file(self):
        encrypted = os.path.join(self.root, "disk.raw.gz.age")
        with open(encrypted, "wb") as stream:
            stream.write(b"ciphertext")
        def fake_run(command, **kwargs):
            output = command[command.index("--output") + 1]
            with open(output, "wb") as stream:
                stream.write(b"compressed bytes")
            return SimpleNamespace(returncode=0, stderr="")
        with patch("feclora.storage.image_security.subprocess.run", side_effect=fake_run):
            staged = decrypt_artifact_to_temp(
                encrypted, self.identity, self.root, age_executable="/usr/bin/age"
            )
        self.addCleanup(lambda: os.path.exists(staged) and os.unlink(staged))
        self.assertEqual(open(staged, "rb").read(), b"compressed bytes")
        self.assertEqual(os.stat(staged).st_mode & 0o777, 0o600)

    def test_sign_and_verify_manifest(self):
        signature = self.manifest + ".minisig"
        def fake_run(command, **kwargs):
            if "-S" in command:
                with open(signature, "wb") as stream:
                    stream.write(b"signature")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        with patch("feclora.storage.image_security.subprocess.run", side_effect=fake_run):
            self.assertEqual(sign_manifest(self.manifest, self.secret, minisign_executable="/usr/bin/minisign"), signature)
            verify_manifest_signature(
                self.manifest, self.public, minisign_executable="/usr/bin/minisign"
            )

    def test_verification_failure_is_rejected(self):
        signature = self.manifest + ".minisig"
        with open(signature, "wb") as stream:
            stream.write(b"bad signature")
        with patch("feclora.storage.image_security.subprocess.run",
                   return_value=SimpleNamespace(returncode=1, stderr="signature mismatch", stdout="")):
            with self.assertRaisesRegex(ImageSecurityError, "invalid"):
                verify_manifest_signature(self.manifest, self.public, minisign_executable="/usr/bin/minisign")


    def test_preflight_checks_only_selected_optional_integrations(self):
        with patch("feclora.storage.image_security.shutil.which", return_value=None):
            preflight_image_security()
            with self.assertRaisesRegex(ImageSecurityError, "age executable is required"):
                preflight_image_security(age_recipients_file=self.recipients)
            with self.assertRaisesRegex(ImageSecurityError, "minisign executable is required"):
                preflight_image_security(minisign_secret_key=self.secret)

    def test_preflight_rejects_missing_selected_key_file(self):
        with self.assertRaisesRegex(ImageSecurityError, "age recipients file is unavailable"):
            preflight_image_security(age_recipients_file=os.path.join(self.root, "missing-recipients"))


if __name__ == "__main__":
    unittest.main()
