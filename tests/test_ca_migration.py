import json
import os
import stat
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.ca_migration import CAMigrationError, CAMigrationStore


class CAMigrationStoreTests(unittest.TestCase):
    def store(self, directory):
        real_fstat = os.fstat

        def safe_fstat(fd):
            info = real_fstat(fd)
            return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_size=info.st_size)

        stack = (
            patch("feclora.deployment.ca_migration.os.geteuid", return_value=0),
            patch("feclora.deployment.ca_migration._directory", side_effect=lambda path: os.path.abspath(path)),
            patch("feclora.deployment.ca_migration.os.fstat", side_effect=safe_fstat),
        )
        for item in stack:
            item.start()
            self.addCleanup(item.stop)
        return CAMigrationStore(directory)

    def test_manifest_survives_reload_and_enforces_all_client_acknowledgements(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            migration = store.create("a" * 64, "b" * 64, ["client-a", "client-b"])
            identifier = migration["migration_id"]
            store.begin_distribution(identifier)
            store.acknowledge_trust(identifier, "client-a")
            with self.assertRaisesRegex(CAMigrationError, "remain unacknowledged"):
                store.complete_distribution(identifier)
            store.acknowledge_trust(identifier, "client-b")
            self.assertEqual(store.complete_distribution(identifier)["phase"], "trust_distributed")
            self.assertEqual(CAMigrationStore(directory).get(identifier)["phase"], "trust_distributed")

    def test_state_machine_requires_ordered_leaf_acknowledgements_and_explicit_retirement(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            identifier = store.create("a" * 64, "b" * 64, ["client-a"])["migration_id"]
            store.begin_distribution(identifier)
            store.acknowledge_trust(identifier, "client-a")
            store.complete_distribution(identifier)
            store.record_server_switch(identifier)
            with self.assertRaisesRegex(CAMigrationError, "unacknowledged"):
                store.mark_converged(identifier)
            store.acknowledge_new_leaf(identifier, "client-a")
            store.mark_converged(identifier)
            with self.assertRaisesRegex(CAMigrationError, "explicit confirmation"):
                store.retire_old_trust(identifier, confirmed=False)
            self.assertEqual(store.retire_old_trust(identifier, confirmed=True)["phase"], "retired")

    def test_unknown_clients_and_out_of_order_transitions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            identifier = store.create("a" * 64, "b" * 64, ["client-a"])["migration_id"]
            with self.assertRaises(CAMigrationError):
                store.acknowledge_trust(identifier, "unknown")
            with self.assertRaises(CAMigrationError):
                store.record_server_switch(identifier)

    def test_rejects_duplicate_clients_equal_fingerprints_and_duplicate_migration_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            with self.assertRaises(CAMigrationError):
                store.create("a" * 64, "b" * 64, ["client-a", "client-a"])
            with self.assertRaises(CAMigrationError):
                store.create("a" * 64, "a" * 64, [])
            identifier = str(uuid.uuid4())
            store.create("a" * 64, "b" * 64, [], migration_id=identifier)
            with self.assertRaisesRegex(CAMigrationError, "already exists"):
                store.create("a" * 64, "c" * 64, [], migration_id=identifier)

    def test_corrupt_or_unsafe_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            identifier = store.create("a" * 64, "b" * 64, [])["migration_id"]
            path = os.path.join(directory, identifier + ".json")
            with open(path, "w", encoding="ascii") as stream:
                stream.write('{"schema_version":1,"schema_version":1}')
            with self.assertRaisesRegex(CAMigrationError, "duplicate JSON"):
                store.get(identifier)
            os.chmod(path, 0o644)
            with self.assertRaisesRegex(CAMigrationError, "permissions"):
                store.get(identifier)


if __name__ == "__main__":
    unittest.main()
