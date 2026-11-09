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
                "encrypt": False, "sign": False,
            })
            status = store.status(operation_id)
            self.assertEqual(status["state"], "queued")
            self.assertEqual(status["events"][0]["sequence"], 1)
            self.assertEqual(store.definition(operation_id)["params"]["source"], "/dev/sda")

    def test_enforces_state_machine_and_hash_chain(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, "sign": False,
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
                "encrypt": False, "sign": False,
            })
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            store.append(identifier, "progress", {"bytes_done": 1024})
            self.assertEqual(store.status(identifier)["state"], "running")
            store.append(identifier, "verifying")
            store.append(identifier, "completed")
            self.assertEqual(store.status(identifier)["state"], "completed")

    def test_running_destructive_write_cannot_be_cancelled(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("restore_disk", {
                "image_id": "gold", "target": "/dev/sdb",
                "confirmation": "ERASE /dev/sdb",
            })
            store.append(identifier, "preflight")
            store.append(identifier, "running")
            with self.assertRaisesRegex(LocalOperationError, "invalid operation transition"):
                store.append(identifier, "cancelled")

    def test_list_returns_durable_operation_status(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, "sign": False,
            })
            reports = store.list()
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["operation_id"], identifier)
            self.assertEqual(reports[0]["state"], "queued")
            all_reports = store.list_all()
            self.assertEqual([item["operation_id"] for item in all_reports], [identifier])

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
