import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage.sftp_repository_registry import (
    SFTPRepositoryRegistry, SFTPRepositoryRegistryError,
)


class SFTPRepositoryRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = SFTPRepositoryRegistry(
            self.root / "sftp-repositories.json",
            owner_uid=os.getuid(), effective_uid=lambda: 0,
        )
        self.definition = {
            "id": "offsite-backup",
            "host": "backup.example.net",
            "username": "backup",
            "remote_directory": "/images/nightly",
            "port": 2222,
            "identity_credential": "/etc/credstore.encrypted/feclora/backup-key.cred",
            "known_hosts_credential": "/etc/credstore.encrypted/feclora/backup-hosts.cred",
        }

    def test_save_list_update_and_remove_saved_endpoint(self):
        with patch("feclora.storage.sftp_repository_registry._credential"):
            saved = self.registry.save(self.definition)
            self.assertEqual(saved, self.definition)
            listed = self.registry.list()
            expected = {key: value for key, value in self.definition.items() if key != "id"}
            self.assertEqual(listed, [expected])
            updated = dict(self.definition, remote_directory="/images/releases")
            self.registry.save(updated)
            self.assertEqual(self.registry.list()[0]["remote_directory"], "/images/releases")
            self.registry.remove("offsite-backup")
            self.assertEqual(self.registry.list(), [])

    def test_rejects_path_traversal_before_persisting(self):
        invalid = dict(self.definition, remote_directory="/images/../escape")
        with patch("feclora.storage.sftp_repository_registry._credential"):
            with self.assertRaisesRegex(SFTPRepositoryRegistryError, "absolute and normalized"):
                self.registry.save(invalid)
        self.assertEqual(self.registry.list(), [])

    def test_rejects_unregistered_credential_reference(self):
        invalid = dict(self.definition, identity_credential="/tmp/private-key")
        with self.assertRaisesRegex(SFTPRepositoryRegistryError, "registered encrypted credential"):
            self.registry.save(invalid)

    def test_registry_file_is_private_and_contains_only_references(self):
        with patch("feclora.storage.sftp_repository_registry._credential"):
            self.registry.save(self.definition)
        info = os.stat(self.root / "sftp-repositories.json")
        self.assertEqual(info.st_mode & 0o777, 0o600)
        raw = (self.root / "sftp-repositories.json").read_text(encoding="utf-8")
        self.assertIn("identity_credential", raw)
        self.assertNotIn("private key contents", raw)


if __name__ == "__main__":
    unittest.main()
