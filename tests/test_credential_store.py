import os
import tempfile
import unittest
from pathlib import Path

from feclora.storage.credential_store import CredentialStore, CredentialStoreError


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "credentials"
        self.store = CredentialStore(self.root, effective_uid=lambda: 0, owner_uid=os.getuid())

    def test_create_is_private_and_returns_only_reference_path(self):
        path = self.store.put("nas", "ssh-key", b"PRIVATE KEY")
        self.assertEqual(path, str(self.root / "nas.ssh-key"))
        self.assertEqual((self.root / "nas.ssh-key").read_bytes(), b"PRIVATE KEY")
        self.assertEqual((self.root / "nas.ssh-key").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_create_never_overwrites_existing_credential(self):
        self.store.put("nas", "smb", b"old")
        with self.assertRaisesRegex(CredentialStoreError, "explicit replacement"):
            self.store.put("nas", "smb", b"new")
        self.assertEqual((self.root / "nas.smb").read_bytes(), b"old")

    def test_explicit_replace_is_atomic_and_preserves_private_mode(self):
        self.store.put("nas", "smb", b"old")
        self.store.put("nas", "smb", b"new", replace=True)
        path = self.root / "nas.smb"
        self.assertEqual(path.read_bytes(), b"new")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rclone_credential_kind_is_not_supported(self):
        with self.assertRaises(CredentialStoreError):
            self.store.put("nas", "rclone", b"config")

    def test_known_hosts_uses_read_only_public_mode(self):
        self.store.put("nas", "known-hosts", b"nas ssh-ed25519 AAAA")
        self.assertEqual((self.root / "nas.known-hosts").stat().st_mode & 0o777, 0o644)

    def test_known_hosts_can_be_replaced_and_removed(self):
        self.store.put("nas", "known-hosts", b"old host key")
        self.store.put("nas", "known-hosts", b"new host key", replace=True)
        path = self.root / "nas.known-hosts"
        self.assertEqual(path.read_bytes(), b"new host key")
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.store.remove("nas", "known-hosts")
        self.assertFalse(path.exists())

    def test_rejects_symlinked_store_directory(self):
        real = Path(self.temp.name) / "real"
        real.mkdir(mode=0o700)
        self.root.symlink_to(real)
        with self.assertRaisesRegex(CredentialStoreError, "private owner-controlled"):
            self.store.put("nas", "ssh-key", b"secret")

    def test_rejects_unsafe_existing_file_before_replace_or_remove(self):
        self.store.put("nas", "ssh-key", b"secret")
        path = self.root / "nas.ssh-key"
        path.chmod(0o644)
        with self.assertRaisesRegex(CredentialStoreError, "unsafe ownership"):
            self.store.put("nas", "ssh-key", b"new", replace=True)
        with self.assertRaisesRegex(CredentialStoreError, "unsafe ownership"):
            self.store.remove("nas", "ssh-key")

    def test_list_returns_only_validated_references(self):
        self.store.put("nas", "ssh-key", b"private")
        self.store.put("nas", "known-hosts", b"host key")
        entries = self.store.list()
        self.assertEqual(entries, [
            {"id": "nas", "kind": "known-hosts", "path": str(self.root / "nas.known-hosts")},
            {"id": "nas", "kind": "ssh-key", "path": str(self.root / "nas.ssh-key")},
        ])
        self.assertNotIn("private", repr(entries))

    def test_list_requires_root(self):
        self.store.put("nas", "smb", b"username=x")
        unprivileged = CredentialStore(self.root, effective_uid=lambda: 1000, owner_uid=os.getuid())
        with self.assertRaisesRegex(CredentialStoreError, "requires root"):
            unprivileged.list()

    def test_remove_validates_then_deletes(self):
        self.store.put("nas", "smb", b"username=x")
        self.store.remove("nas", "smb")
        self.assertFalse((self.root / "nas.smb").exists())

    def test_rejects_invalid_content_and_non_root_callers(self):
        for value in (b"", b"bad\x00secret", "not-bytes"):
            with self.subTest(value=value):
                with self.assertRaises(CredentialStoreError):
                    self.store.put("nas", "ssh-key", value)
        unprivileged = CredentialStore(self.root, effective_uid=lambda: 1000, owner_uid=os.getuid())
        with self.assertRaisesRegex(CredentialStoreError, "requires root"):
            unprivileged.put("nas", "ssh-key", b"secret")
