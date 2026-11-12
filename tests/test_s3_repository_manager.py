import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.storage.s3_repository_manager import (
    S3RepositoryManager, S3RepositoryManagerError,
)


class FakeCredentials:
    def __init__(self):
        self.values = {"archive": b'{"access_key_id":"AKIA0123456789ABCD","secret_access_key":"secret-access-key"}'}

    def read(self, identifier, kind):
        if kind != "s3" or identifier not in self.values:
            raise RuntimeError("credential unavailable")
        return self.values[identifier]

    def _path(self, identifier, kind):
        return Path("/etc/credstore.encrypted/feclora") / f"feclora-{identifier}-{kind}.cred"

    def _validate_existing(self, path):
        if path.name != "feclora-archive-s3.cred":
            raise RuntimeError("missing credential")


class S3RepositoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = Path(self.temp.name) / "etc" / "s3-repositories.json"
        self.credentials = FakeCredentials()
        self.manager = S3RepositoryManager(
            registry=self.registry, credentials=self.credentials,
            effective_uid=lambda: 0, owner_uid=os.getuid(),
        )
        self.definition = {
            "endpoint_url": "https://s3.example.net",
            "region": "us-east-1", "bucket": "feclora-backups",
            "prefix": "images/server-a", "credential_id": "archive",
            "read_only": False,
        }

    def test_add_and_list_persist_only_metadata_and_credential_reference(self):
        self.manager.add("archive", self.definition)
        listed = self.manager.list()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["provider"], "s3")
        self.assertEqual(listed[0]["credential_id"], "archive")
        self.assertEqual(listed[0]["credential_refs"], [
            "/etc/credstore.encrypted/feclora/feclora-archive-s3.cred"
        ])
        raw = self.registry.read_text()
        self.assertNotIn("secret-access-key", raw)
        self.assertNotIn("AKIA0123456789ABCD", raw)
        self.assertEqual(json.loads(raw)["repositories"]["archive"], self.definition)
        self.assertEqual(self.registry.stat().st_mode & 0o777, 0o600)

    def test_rejects_invalid_endpoint_and_unknown_fields(self):
        invalid = dict(self.definition, endpoint_url="http://s3.example.net")
        with self.assertRaises(S3RepositoryManagerError):
            self.manager.add("archive", invalid)
        invalid = dict(self.definition, unexpected="value")
        with self.assertRaisesRegex(S3RepositoryManagerError, "missing or unknown"):
            self.manager.add("archive", invalid)

    def test_credential_reference_prevents_credential_removal(self):
        self.manager.add("archive", self.definition)
        self.assertTrue(self.manager.credential_is_referenced("archive"))
        self.assertFalse(self.manager.credential_is_referenced("other"))

    def test_update_and_remove(self):
        self.manager.add("archive", self.definition)
        updated = dict(self.definition, read_only=True)
        self.manager.update("archive", updated)
        self.assertTrue(self.manager.list()[0]["read_only"])
        self.assertEqual(self.manager.remove("archive"), {"id": "archive", "removed": True})
        self.assertEqual(self.manager.list(), [])

    def test_active_usage_lease_blocks_repository_update_and_remove(self):
        self.manager.add("archive", self.definition)
        lease = self.manager.acquire_usage_lock("archive")
        try:
            with self.assertRaisesRegex(S3RepositoryManagerError, "in use"):
                self.manager.update("archive", dict(self.definition, read_only=True))
            with self.assertRaisesRegex(S3RepositoryManagerError, "in use"):
                self.manager.remove("archive")
        finally:
            os.close(lease)
        self.manager.update("archive", dict(self.definition, read_only=True))
        self.assertTrue(self.manager.list()[0]["read_only"])

    def test_repository_decrypts_credential_only_when_requested(self):
        self.manager.add("archive", self.definition)
        with patch("feclora.storage.s3_repository_manager.S3ObjectRepository") as client:
            result = self.manager.repository("archive")
        config = client.call_args.args[0]
        self.assertEqual(config.access_key_id, "AKIA0123456789ABCD")
        self.assertEqual(config.secret_access_key, "secret-access-key")
        self.assertEqual(config.bucket, "feclora-backups")
        self.assertEqual(result, client.return_value)


if __name__ == "__main__":
    unittest.main()
