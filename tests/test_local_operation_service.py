import json
import os
import tempfile
import unittest
from unittest.mock import patch

from feclora.storage.local_operations import LocalOperationStore
from feclora.storage.local_operation_service import _ProgressForwarder, recover_interrupted


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

    def test_recovery_continues_after_one_damaged_journal(self):
        store = unittest.mock.Mock()
        store.operation_ids.return_value = ["running-job", "damaged-job", "finished-job"]
        store.status.side_effect = [
            {"state": "running"},
            RuntimeError("invalid event hash"),
            {"state": "completed"},
        ]
        with patch("feclora.storage.local_operation_service.LocalOperationStore",
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
