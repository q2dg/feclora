import json
import os
import tempfile
import unittest
from feclora.storage.local_operations import (
    LocalOperationError, LocalOperationStore, validate_definition,
)

class LocalOperationStoreTests(unittest.TestCase):
    def test_submit_persists_definition_and_queued_event(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            operation_id = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
            })
            status = store.status(operation_id)
            self.assertEqual(status["state"], "queued")
            self.assertEqual(status["events"][0]["sequence"], 1)
            self.assertEqual(store.definition(operation_id)["params"]["source"], "/dev/sda")

    def test_logical_volume_capture_is_a_valid_durable_operation(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "capture_logical_volume",
            "params": {
                "source": "/dev/mapper/vg-root", "image_id": "root-image",
                "compression": "zstd", "encrypt": False, 
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["action"], "capture_logical_volume")
        self.assertEqual(validated["params"]["source"], "/dev/mapper/vg-root")

    def test_logical_volume_restore_is_a_valid_durable_operation(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000002",
            "action": "restore_logical_volume",
            "params": {
                "image_id": "root-image", "target": "/dev/mapper/vg-root",
                "confirmation": "ERASE /dev/mapper/vg-root",
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["action"], "restore_logical_volume")
        self.assertEqual(validated["params"]["target"], "/dev/mapper/vg-root")

    def test_sftp_inventory_is_a_valid_durable_operation(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "sftp_inventory",
            "params": {
                "host": "backup.example.net", "username": "backup",
                "remote_directory": "/", "port": 22,
                "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["action"], "sftp_inventory")

    def test_sftp_fetch_and_publish_are_valid_durable_operations(self):
        common = {
            "host": "backup.example.net", "username": "backup",
            "remote_directory": "/images/golden", "port": 22,
            "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
            "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
        }
        for action, params in (("sftp_fetch", common),
                               ("sftp_publish", {"image_id": "golden", **common})):
            definition = {
                "schema_version": 1,
                "operation_id": "00000000-0000-4000-8000-000000000001",
                "action": action, "params": params,
            }
            self.assertEqual(validate_definition(definition)["action"], action)

    def test_sftp_fetch_rejects_unregistered_credential_path(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "sftp_fetch",
            "params": {
                "host": "backup.example.net", "username": "backup",
                "remote_directory": "/images", "port": 22,
                "identity_credential": "/tmp/private.key",
                "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
            },
        }
        with self.assertRaisesRegex(LocalOperationError, "registered encrypted credential"):
            validate_definition(definition)
    def test_sftp_inventory_rejects_path_traversal(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "sftp_inventory",
            "params": {
                "host": "backup.example.net", "username": "backup",
                "remote_directory": "/images/../escape", "port": 22,
                "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
            },
        }
        with self.assertRaisesRegex(LocalOperationError, "absolute and normalized"):
            validate_definition(definition)

    def test_capture_can_include_encrypted_sftp_publication_settings(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "capture_disk",
            "params": {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
                "sftp_publish": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/images/daily", "port": 2222,
                    "identity_credential": "/etc/credstore.encrypted/feclora/backup-key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/backup-hosts.cred",
                },
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["params"]["sftp_publish"]["port"], 2222)

    def test_capture_allows_sftp_publication_to_remote_root(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "capture_disk",
            "params": {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
                "sftp_publish": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/",
                    "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
                },
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["params"]["sftp_publish"]["remote_directory"], "/")

    def test_capture_rejects_sftp_publication_path_traversal_before_queueing(self):
        for remote_directory in (
            "/images/../escape", "/images/./daily", "/images//daily",
            "//backup/images", "/images/../../etc", "/images/space name",
        ):
            with self.subTest(remote_directory=remote_directory):
                definition = {
                    "schema_version": 1,
                    "operation_id": "00000000-0000-4000-8000-000000000001",
                    "action": "capture_disk",
                    "params": {
                        "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                        "encrypt": False, 
                        "sftp_publish": {
                            "host": "backup.example.net", "username": "backup",
                            "remote_directory": remote_directory,
                            "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                            "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
                        },
                    },
                }
                with self.assertRaisesRegex(LocalOperationError, "absolute and normalized"):
                    validate_definition(definition)

    def test_capture_sftp_publication_does_not_require_image_signing(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "capture_disk",
            "params": {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
                "sftp_publish": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/images/daily",
                    "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
                },
            },
        }
        validate_definition(definition)

    def test_enforces_state_machine_and_hash_chain(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
            })
            with self.assertRaisesRegex(LocalOperationError, "invalid operation transition"):
                store.append(identifier, "completed")
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            store.append(identifier, "progress", {"bytes_done": 1024})
            store.append(identifier, "verifying")
            store.append(identifier, "completed")
            self.assertEqual(store.status(identifier)["state"], "completed")

    def test_restart_recovery_marks_job_interrupted_without_replay(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("restore_disk", {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb",
            })
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            recovered = store.mark_interrupted(identifier)
            self.assertEqual(recovered["state"], "interrupted")
            self.assertEqual(store.status(identifier)["state"], "interrupted")


    def test_restore_can_use_encrypted_sftp_source(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "restore_disk",
            "params": {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb",
                "sftp_source": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/images/gold", "port": 2222,
                    "expected_manifest_sha256": "a" * 64,
                    "identity_credential": "/etc/credstore.encrypted/feclora/backup-key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/backup-hosts.cred",
                },
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["params"]["sftp_source"]["remote_directory"], "/images/gold")

    def test_restore_rejects_sftp_source_combined_with_mounted_repository(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "restore_disk",
            "params": {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb", "repository_id": "archive",
                "sftp_source": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/images", "expected_manifest_sha256": "a" * 64,
                    "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
                },
            },
        }
        with self.assertRaisesRegex(LocalOperationError, "cannot be combined"):
            validate_definition(definition)

    def test_restore_allows_sftp_source_remote_root(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "restore_disk",
            "params": {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb",
                "sftp_source": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/", "expected_manifest_sha256": "a" * 64,
                    "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
                },
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["params"]["sftp_source"]["remote_directory"], "/")

    def test_restore_rejects_sftp_source_path_traversal(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "restore_disk",
            "params": {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb",
                "sftp_source": {
                    "host": "backup.example.net", "username": "backup",
                    "remote_directory": "/images/../escape", "expected_manifest_sha256": "a" * 64,
                    "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                    "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
                },
            },
        }
        with self.assertRaisesRegex(LocalOperationError, "absolute and normalized"):
            validate_definition(definition)

    def test_rejects_bad_destructive_confirmation(self):
        with self.assertRaisesRegex(LocalOperationError, "confirmation"):
            validate_definition({
                "schema_version": 1, "operation_id": "00000000-0000-4000-8000-000000000001",
                "action": "restore_disk", "params": {
                    "image_id": "gold", "target": "/dev/sdb", "confirmation": "ERASE /dev/sda",
                },
            })

    def test_rejects_unknown_fields_and_actions(self):
        payload = {
            "schema_version": 1, "operation_id": "00000000-0000-4000-8000-000000000001",
            "action": "run_shell", "params": {"command": "id"},
        }
        with self.assertRaises(LocalOperationError):
            validate_definition(payload)

    def test_progress_events_do_not_change_logical_state_or_break_transitions(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
            })
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            store.append(identifier, "progress", {"bytes_done": 1024})
            self.assertEqual(store.status(identifier)["state"], "running")
            store.append(identifier, "verifying")
            store.append(identifier, "completed")
            self.assertEqual(store.status(identifier)["state"], "completed")

    def test_running_operation_can_transition_to_cancelled(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
            })
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            store.append(identifier, "cancelled", {
                "reason": "operator requested cancellation",
                "destination_may_be_partial": False,
            })
            report = store.status(identifier)
            self.assertEqual(report["state"], "cancelled")
            self.assertFalse(report["events"][-1]["details"]["destination_may_be_partial"])

    def test_running_destructive_write_records_possible_partial_destination_on_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("restore_disk", {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb",
            })
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            store.append(identifier, "cancelled", {
                "reason": "operator requested cancellation",
                "destination_may_be_partial": True,
            })
            report = store.status(identifier)
            self.assertEqual(report["state"], "cancelled")
            self.assertTrue(report["events"][-1]["details"]["destination_may_be_partial"])

    def test_list_returns_durable_operation_status(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, 
            })
            reports = store.list()
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["operation_id"], identifier)
            self.assertEqual(reports[0]["state"], "queued")
            all_reports = store.list_all()
            self.assertEqual([item["operation_id"] for item in all_reports], [identifier])

    def test_list_all_includes_jobs_older_than_recent_history_limit(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            params = {"source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                      "encrypt": False, "sign": False}
            for _ in range(501):
                store.submit("capture_disk", params)
            self.assertEqual(len(store.list(limit=500)), 500)
            self.assertEqual(len(store.list_all()), 501)

    def test_duplicate_submission_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = "00000000-0000-4000-8000-000000000001"
            params = {"source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                      "encrypt": False, "sign": False}
            store.submit("capture_disk", params, operation_id=identifier)
            with self.assertRaisesRegex(LocalOperationError, "already exists"):
                store.submit("capture_disk", params, operation_id=identifier)

if __name__ == "__main__":
    unittest.main()
