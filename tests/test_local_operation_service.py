import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from feclora.storage.local_operations import LocalOperationStore
from feclora.storage.local_operation_service import _ProgressForwarder, _cancel_on_sigterm, LocalOperationCancelled, execute, recover_interrupted


class LocalOperationWorkerTests(unittest.TestCase):
    def test_progress_is_written_to_durable_journal(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            operation_id = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, "sign": False,
            })
            store.append(operation_id, "preflight")
            store.append(operation_id, "running")
            forwarder = _ProgressForwarder(store, operation_id)
            payload = json.dumps({
                "event": "progress", "bytes_done": 4096, "bytes_total": 8192,
                "message": "copying",
            }) + "\n"
            forwarder.write(payload)
            forwarder.flush()
            report = store.status(operation_id)
            self.assertEqual(report["state"], "running")
            self.assertEqual(report["events"][-1]["details"]["bytes_done"], 4096)
            self.assertEqual(report["events"][-1]["details"]["bytes_total"], 8192)

    def test_sigterm_handler_requests_orderly_worker_cancellation(self):
        with self.assertRaisesRegex(LocalOperationCancelled, "cancellation requested"):
            _cancel_on_sigterm(15, None)

    def test_worker_records_cancelled_state_and_partial_restore_warning(self):
        store = Mock()
        store.definition.return_value = {
            "action": "restore_disk",
            "params": {"image_id": "gold", "target": "/dev/sdb", "confirmation": "ERASE /dev/sdb"},
        }
        store.status.side_effect = [{"state": "queued"}, {"state": "running"}]
        with patch("feclora.storage.local_operation_service.os.geteuid", return_value=0), \
             patch("feclora.storage.local_operation_service.LocalOperationStore", return_value=store), \
             patch("feclora.storage.local_operation_service._device_lock_fds", return_value=[]), \
             patch("feclora.webapi._storage_operation_lock", return_value=nullcontext()), \
             patch("feclora.webapi._execute_operation", side_effect=LocalOperationCancelled("stop")):
            self.assertEqual(execute("00000000-0000-4000-8000-000000000001"), 0)
        self.assertEqual(store.append.call_args_list[-1].args[1], "cancelled")
        details = store.append.call_args_list[-1].args[2]
        self.assertTrue(details["destination_may_be_partial"])

    def test_worker_persists_validated_sftp_inventory_manifest_names(self):
        store = Mock()
        store.definition.return_value = {
            "action": "sftp_inventory",
            "params": {
                "host": "backup.example.net", "username": "backup",
                "remote_directory": "/images", "port": 22,
                "identity_credential": "/etc/credstore.encrypted/feclora/key.cred",
                "known_hosts_credential": "/etc/credstore.encrypted/feclora/hosts.cred",
            },
        }
        store.status.return_value = {"state": "queued"}
        with patch("feclora.storage.local_operation_service.os.geteuid", return_value=0), \
             patch("feclora.storage.local_operation_service.LocalOperationStore", return_value=store), \
             patch("feclora.storage.local_operation_service._device_lock_fds", return_value=[]), \
             patch("feclora.webapi._storage_operation_lock", return_value=nullcontext()), \
             patch("feclora.webapi._execute_operation", return_value={
                 "operation": "inventory", "completed": True,
                 "manifests": ["manifest.json", "daily.manifest.json"],
             }):
            self.assertEqual(execute("00000000-0000-4000-8000-000000000001"), 0)
        self.assertEqual(store.append.call_args_list[-1].args[1], "completed")
        self.assertEqual(store.append.call_args_list[-1].args[2]["manifests"],
                         ["manifest.json", "daily.manifest.json"])

    def test_worker_persists_sftp_fetch_result_and_artifact_progress(self):
        store = Mock()
        store.definition.return_value = {
            "action": "sftp_fetch",
            "params": {"host": "backup.example.net"},
        }
        store.status.return_value = {"state": "queued"}
        with patch("feclora.storage.local_operation_service.os.geteuid", return_value=0), \
             patch("feclora.storage.local_operation_service.LocalOperationStore", return_value=store), \
             patch("feclora.storage.local_operation_service._device_lock_fds", return_value=[]), \
             patch("feclora.webapi._storage_operation_lock", return_value=nullcontext()), \
             patch("feclora.webapi._execute_operation", return_value={
                 "image_id": "golden", "image_type": "disk", "artifact_count": 2,
                 "signature_verified": True, "artifacts_verified": True, "published": True,
             }):
            self.assertEqual(execute("00000000-0000-4000-8000-000000000001"), 0)
        completed = store.append.call_args_list[-1].args[2]
        self.assertEqual(completed["artifact_count"], 2)
        self.assertTrue(completed["signature_verified"])
        self.assertTrue(completed["artifacts_verified"])
    def test_recovery_continues_after_one_damaged_journal(self):
        store = Mock()
        store.operation_ids.return_value = ["running-job", "damaged-job", "finished-job"]
        store.status.side_effect = [
            {"state": "running"},
            RuntimeError("invalid event hash"),
            {"state": "completed"},
        ]
        with patch("feclora.storage.local_operation_service.os.geteuid", return_value=0), \
             patch("feclora.storage.local_operation_service.LocalOperationStore",
                   return_value=store):
            self.assertEqual(recover_interrupted(), 1)
        store.mark_interrupted.assert_called_once_with("running-job")

    def test_progress_forwarder_ignores_non_progress_output(self):
        with tempfile.TemporaryDirectory() as root:
            store = LocalOperationStore(os.path.join(root, "jobs"))
            operation_id = store.submit("capture_disk", {
                "source": "/dev/sda", "image_id": "daily", "compression": "zstd",
                "encrypt": False, "sign": False,
            })
            store.append(operation_id, "preflight")
            store.append(operation_id, "running")
            forwarder = _ProgressForwarder(store, operation_id)
            forwarder.write(json.dumps({"event": "started", "operation": "capture_disk"}) + "\n")
            forwarder.flush()
            self.assertEqual(store.status(operation_id)["state"], "running")


if __name__ == "__main__":
    unittest.main()
