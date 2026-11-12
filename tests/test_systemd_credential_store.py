import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from feclora.storage.systemd_credential_store import (
    SystemdCredentialStore, SystemdCredentialStoreError,
)


class SystemdCredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "encrypted"
        self.calls = []

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[1] == "encrypt":
                Path(argv[-1]).write_bytes(b"encrypted:opaque-ciphertext")
                os.chmod(argv[-1], 0o600)
            if argv[1] == "decrypt":
                return SimpleNamespace(returncode=0, stdout=b"decrypted-secret", stderr="")
            return SimpleNamespace(returncode=0, stdout=b"", stderr="")

        self.store = SystemdCredentialStore(
            self.root, effective_uid=lambda: 0, owner_uid=os.getuid(),
            runner=runner, which=lambda name: "/usr/bin/systemd-creds",
        )

    def test_encrypts_without_writing_plaintext_to_store(self):
        result = self.store.put("nas", "ssh-key", b"PRIVATE KEY")
        path = Path(result["path"])
        self.assertEqual(result["name"], "feclora-nas-ssh-key")
        self.assertEqual(path.read_bytes(), b"encrypted:opaque-ciphertext")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[1:4], ["encrypt", "--name=feclora-nas-ssh-key", "--with-key=auto"])
        self.assertEqual(kwargs["input"], b"PRIVATE KEY")
        self.assertNotIn(b"PRIVATE KEY", path.read_bytes())

    def test_create_only_and_explicit_atomic_replace(self):
        self.store.put("nas", "smb", b"old")
        with self.assertRaisesRegex(SystemdCredentialStoreError, "explicit replacement"):
            self.store.put("nas", "smb", b"new")
        self.store.put("nas", "smb", b"new", replace=True)
        self.assertEqual((self.root / "feclora-nas-smb.cred").read_bytes(), b"encrypted:opaque-ciphertext")

    def test_list_returns_validated_metadata_only(self):
        self.store.put("nas", "ssh-key", b"secret")
        entries = self.store.list()
        self.assertEqual(entries, [{
            "id": "nas", "kind": "ssh-key", "name": "feclora-nas-ssh-key",
            "path": str(self.root / "feclora-nas-ssh-key.cred"),
        }])
        self.assertNotIn("secret", repr(entries))

    def test_s3_credentials_are_schema_checked_and_decrypted_only_to_memory(self):
        valid = b'{"access_key_id":"AKIA0123456789ABCD","secret_access_key":"test-secret-value"}'
        result = self.store.put("archive", "s3", valid)
        self.assertEqual(result["kind"], "s3")
        entries = self.store.list()
        self.assertTrue(any(item["kind"] == "s3" for item in entries))
        self.assertEqual(self.store.read("archive", "s3"), b"decrypted-secret")
        argv, kwargs = self.calls[-1]
        self.assertEqual(argv[1:3], ["decrypt", "--name=feclora-archive-s3"])
        self.assertEqual(argv[-1], "-")
        self.assertEqual(kwargs["capture_output"], True)
        with self.assertRaisesRegex(SystemdCredentialStoreError, "S3 credential JSON"):
            self.store.put("invalid", "s3", b'{"secret_access_key":"only-secret"}')

    def test_empty_inventory_initializes_private_credential_directory(self):
        entries = self.store.list()
        self.assertEqual(entries, [])
        self.assertTrue(self.root.is_dir())
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_rejects_symlinked_existing_credential(self):
        self.store.put("nas", "ssh-key", b"secret")
        path = self.root / "feclora-nas-ssh-key.cred"
        external = Path(self.temp.name) / "external"
        external.write_bytes(b"encrypted")
        path.unlink()
        path.symlink_to(external)
        with self.assertRaises(SystemdCredentialStoreError):
            self.store.remove("nas", "ssh-key")

    def test_rejects_nul_and_failed_encryption_without_publishing(self):
        with self.assertRaises(SystemdCredentialStoreError):
            self.store.put("nas", "smb", b"bad\x00secret")
        self.assertFalse(self.root.exists())

        def failed_runner(argv, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="private details")

        failed = SystemdCredentialStore(
            self.root, effective_uid=lambda: 0, owner_uid=os.getuid(),
            runner=failed_runner, which=lambda name: "/usr/bin/systemd-creds",
        )
        with self.assertRaisesRegex(SystemdCredentialStoreError, "could not encrypt"):
            failed.put("nas", "smb", b"secret")
        self.assertEqual(list(self.root.glob("*.cred")), [])

    def test_requires_root_and_systemd_creds(self):
        non_root = SystemdCredentialStore(
            self.root, effective_uid=lambda: 1000, owner_uid=os.getuid(),
            runner=self.store.runner, which=self.store.which,
        )
        with self.assertRaisesRegex(SystemdCredentialStoreError, "requires root"):
            non_root.put("nas", "smb", b"secret")
        unavailable = SystemdCredentialStore(
            self.root, effective_uid=lambda: 0, owner_uid=os.getuid(),
            runner=self.store.runner, which=lambda name: None,
        )
        with self.assertRaisesRegex(SystemdCredentialStoreError, "systemd-creds is required"):
            unavailable.put("nas", "smb", b"secret")


if __name__ == "__main__":
    unittest.main()
