from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feclora.deployment.client_service import mark_client_job_interrupted


JOB_ID = "3b241101-e2bb-4255-8caf-4136c566a962"


class ClientJobInterruptionRecoveryTests(unittest.TestCase):
    def test_nonterminal_status_is_marked_interrupted_without_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "job.status.json"
            status_path.write_text("{}", encoding="utf-8")
            status = {"phase": "running", "success": None, "detail": "in progress"}
            with patch(
                "feclora.deployment.client_service._job_paths",
                return_value=(Path(directory) / "request.json", status_path, Path(directory) / "lock"),
            ), patch(
                "feclora.deployment.client_service._ensure_directory",
            ), patch(
                "feclora.deployment.client_service._read_private_json",
                return_value=status,
            ) as read_status, patch(
                "feclora.deployment.client_service._write_private_json",
            ) as write_status:
                mark_client_job_interrupted(JOB_ID)

            read_status.assert_called_once_with(status_path, limit=16384)
            written_path, written_status = write_status.call_args.args
            self.assertEqual(written_path, status_path)
            self.assertEqual(written_status["phase"], "interrupted")
            self.assertIs(written_status["success"], False)
            self.assertIn("No automatic reconnect or storage resume", written_status["detail"])
            self.assertIn("updated_at", written_status)

    def test_terminal_status_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "job.status.json"
            status_path.write_text("{}", encoding="utf-8")
            status = {"phase": "completed", "success": True}
            with patch(
                "feclora.deployment.client_service._job_paths",
                return_value=(Path(directory) / "request.json", status_path, Path(directory) / "lock"),
            ), patch(
                "feclora.deployment.client_service._ensure_directory",
            ), patch(
                "feclora.deployment.client_service._read_private_json",
                return_value=status,
            ), patch(
                "feclora.deployment.client_service._write_private_json",
            ) as write_status:
                mark_client_job_interrupted(JOB_ID)
            write_status.assert_not_called()

    def test_missing_status_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "missing.status.json"
            with patch(
                "feclora.deployment.client_service._job_paths",
                return_value=(Path(directory) / "request.json", status_path, Path(directory) / "lock"),
            ), patch(
                "feclora.deployment.client_service._ensure_directory",
            ), patch(
                "feclora.deployment.client_service._read_private_json",
            ) as read_status, patch(
                "feclora.deployment.client_service._write_private_json",
            ) as write_status:
                mark_client_job_interrupted(JOB_ID)
            read_status.assert_not_called()
            write_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
