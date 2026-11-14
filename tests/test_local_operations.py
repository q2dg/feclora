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

    def test_recovery_iso_build_is_a_valid_durable_operation(self):
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000003",
            "action": "build_recovery_iso",
            "params": {
                "base_iso_path": "/home/feclora/live.iso",
                "image_id": "golden",
                "target_wwn": "naa.5000c50012345678",
                "target_serial": None,
                "confirm_build": "BUILD golden",
            },
        }
        validated = validate_definition(definition)
        self.assertEqual(validated["action"], "build_recovery_iso")
        self.assertEqual(validated["params"]["image_id"], "golden")

    def test_recovery_iso_build_rejects_unmatched_confirmation_and_unsafe_path(self):
        params = {
            "base_iso_path": "/home/feclora/live.iso", "image_id": "golden",
            "target_wwn": "naa.5000c50012345678", "target_serial": None,
            "confirm_build": "BUILD other",
        }
        definition = {
            "schema_version": 1,
            "operation_id": "00000000-0000-4000-8000-000000000004",
            "action": "build_recovery_iso", "params": params,
        }
        with self.assertRaisesRegex(LocalOperationError, "confirmation"):
            validate_definition(definition)
        params["confirm_build"] = "BUILD golden"
        params["base_iso_path"] = "/tmp/../etc/passwd"
        with self.assertRaisesRegex(LocalOperationError, "normalized"):
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
                      "encrypt": False}
            for _ in range(501):
                store.submit("capture_disk", params)
            self.assertEqual(len(store.list(limit=500)), 500)
            self.assertEqual(len(store.list_all()), 501)

    def test_duplicate_submission_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            identifier = "00000000-0000-4000-8000-000000000001"
            params = {"source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                      "encrypt": False}
            store.submit("capture_disk", params, operation_id=identifier)
            with self.assertRaisesRegex(LocalOperationError, "already exists"):
                store.submit("capture_disk", params, operation_id=identifier)

if __name__ == "__main__":
    unittest.main()


class P2VLocalOperationSchemaTests(unittest.TestCase):
    def test_p2v_capture_definition_accepts_only_source_image_and_optional_repository(self):
        import uuid
        base = {
            "schema_version": 1, "operation_id": str(uuid.uuid4()),
            "action": "capture_p2v",
            "params": {"source": "/dev/sda", "image_id": "vm-disk", "repository_id": "archive"},
        }
        self.assertEqual(validate_definition(base)["action"], "capture_p2v")
        invalid = dict(base)
        invalid["params"] = {**base["params"], "output_path": "/tmp/unsafe.qcow2"}
        with self.assertRaises(LocalOperationError):
            validate_definition(invalid)



class P2VS3ExportOperationSchemaTests(unittest.TestCase):
    def test_s3_export_definition_accepts_local_or_named_filesystem_destination(self):
        import uuid
        base = {
            "schema_version": 1, "operation_id": str(uuid.uuid4()),
            "action": "export_p2v_s3",
            "params": {"image_id": "vm-disk", "source_repository_id": "s3-archive"},
        }
        self.assertEqual(validate_definition(base)["action"], "export_p2v_s3")
        with_destination = {
            **base, "operation_id": str(uuid.uuid4()),
            "params": {**base["params"], "destination_repository_id": "nfs-images"},
        }
        self.assertEqual(validate_definition(with_destination)["params"]["destination_repository_id"], "nfs-images")

    def test_s3_export_definition_rejects_invalid_repository_ids_and_extra_fields(self):
        import uuid
        base = {
            "schema_version": 1, "operation_id": str(uuid.uuid4()),
            "action": "export_p2v_s3",
            "params": {"image_id": "vm-disk", "source_repository_id": "../escape"},
        }
        with self.assertRaisesRegex(LocalOperationError, "source_repository_id"):
            validate_definition(base)
        base["params"] = {
            "image_id": "vm-disk", "source_repository_id": "s3-archive",
            "output_path": "/tmp/unsafe.qcow2",
        }
        with self.assertRaises(LocalOperationError):
            validate_definition(base)
