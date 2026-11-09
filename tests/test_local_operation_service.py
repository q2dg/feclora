import json
import os
import tempfile
import unittest

from feclora.storage.local_operations import LocalOperationStore
from feclora.storage.local_operation_service import _ProgressForwarder


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
            self.assertEqual(report["state"], "progress")
            self.assertEqual(report["events"][-1]["details"]["bytes_done"], 4096)
            self.assertEqual(report["events"][-1]["details"]["bytes_total"], 8192)

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
