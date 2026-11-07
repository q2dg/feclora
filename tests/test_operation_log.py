import json
import os
import tempfile
import unittest

from feclora.storage.operation_log import OperationLogError, append_event, operation_record


class OperationLogTests(unittest.TestCase):
    def test_records_started_and_completed_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "logs", "operations.jsonl")
            with operation_record("restore_partition", "/dev/sda1", image_id="image-1", log_path=path):
                pass
            with open(path, encoding="utf-8") as stream:
                events = [json.loads(line) for line in stream]
            self.assertEqual([item["status"] for item in events], ["started", "completed"])
            self.assertEqual(events[0]["operation_id"], events[1]["operation_id"])
            self.assertEqual(events[0]["target"], "/dev/sda1")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_records_failure_and_error_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "operations.jsonl")
            with self.assertRaisesRegex(ValueError, "deliberate"):
                with operation_record("capture_disk", "/dev/sdb", log_path=path):
                    raise ValueError("deliberate failure")
            with open(path, encoding="utf-8") as stream:
                events = [json.loads(line) for line in stream]
            self.assertEqual(events[-1]["status"], "failed")
            self.assertEqual(events[-1]["error_type"], "ValueError")

    def test_records_cancellation(self):
        class RestoreCancelled(RuntimeError):
            pass
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "operations.jsonl")
            with self.assertRaises(RestoreCancelled):
                with operation_record("restore_disk", "/dev/sda", log_path=path):
                    raise RestoreCancelled("operator cancelled")
            with open(path, encoding="utf-8") as stream:
                events = [json.loads(line) for line in stream]
            self.assertEqual(events[-1]["status"], "cancelled")

    def test_rejects_symlink_log_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            real_directory = os.path.join(directory, "real")
            os.mkdir(real_directory)
            linked_directory = os.path.join(directory, "linked")
            os.symlink(real_directory, linked_directory)
            with self.assertRaises(OperationLogError):
                append_event(os.path.join(linked_directory, "operations.jsonl"), {"status": "started"})
            self.assertFalse(os.path.exists(os.path.join(real_directory, "operations.jsonl")))

    def test_rejects_symlink_log_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "target")
            link = os.path.join(directory, "operations.jsonl")
            with open(target, "w", encoding="utf-8") as stream:
                stream.write("do not follow")
            os.symlink(target, link)
            with self.assertRaises(OperationLogError):
                append_event(link, {"status": "started"})
            with open(target, encoding="utf-8") as stream:
                self.assertEqual(stream.read(), "do not follow")


if __name__ == "__main__":
    unittest.main()
