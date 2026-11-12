from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from feclora.network.pxe_answer_store import (
    PXEAnswerStoreError, clear_stale_pxe_answers, publish_pxe_answer, revoke_pxe_answer,
)


class PXEAnswerStoreTests(unittest.TestCase):
    JOB_ID = "3b241101-e2bb-4255-8caf-4136c566a962"

    def answer(self):
        return json.dumps({
            "schema_version": 1, "operation": "restore",
            "image_id": "fedora", "repository_url": "sftp://repo.example/images",
            "target": {"wwn": "0x5000abcd", "serial": None},
            "confirm_destructive": True, "start": True,
        }).encode()

    def test_publishes_answer_atomically_and_revokes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o755)
            result = publish_pxe_answer(
                tmp, self.JOB_ID, self.answer(), address="192.0.2.10",
            )
            self.assertTrue(Path(result["directory"], "answer.json").is_file())
            self.assertEqual(Path(result["directory"], "answer.json").stat().st_mode & 0o777, 0o444)
            self.assertEqual(result["answer_url"], f"http://192.0.2.10:8080/answers/{self.JOB_ID}/answer.json")
            published_answer = json.loads(Path(result["directory"], "answer.json").read_text())
            self.assertRegex(published_answer["expires_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

            self.assertTrue(revoke_pxe_answer(tmp, self.JOB_ID))
            self.assertFalse(revoke_pxe_answer(tmp, self.JOB_ID))

    def test_rejects_invalid_answer_and_noncanonical_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o755)
            with self.assertRaises(PXEAnswerStoreError):
                publish_pxe_answer(
                    tmp, self.JOB_ID, b"{}", address="192.0.2.10",
                )
            with self.assertRaises(PXEAnswerStoreError):
                publish_pxe_answer(
                    tmp, str(uuid.UUID(self.JOB_ID)).upper(), self.answer(),
                    address="192.0.2.10",
                )

    def test_clears_all_stale_job_answer_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o755)
            for job_id in (self.JOB_ID, "f47ac10b-58cc-4372-a567-0e02b2c3d480"):
                publish_pxe_answer(
                    tmp, job_id, self.answer(), address="192.0.2.10",
                )
            self.assertEqual(clear_stale_pxe_answers(tmp), 2)
            self.assertEqual(clear_stale_pxe_answers(tmp), 0)
            self.assertFalse((Path(tmp) / "answers" / self.JOB_ID).exists())

    def test_refuses_to_replace_existing_job_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o755)
            args = (tmp, self.JOB_ID, self.answer())
            kwargs = {"address": "192.0.2.10"}
            publish_pxe_answer(*args, **kwargs)
            with self.assertRaisesRegex(PXEAnswerStoreError, "already published"):
                publish_pxe_answer(*args, **kwargs)

    def test_refuses_unsafe_http_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            with self.assertRaises(PXEAnswerStoreError):
                publish_pxe_answer(
                    tmp, self.JOB_ID, self.answer(), address="192.0.2.10",
                )


if __name__ == "__main__":
    unittest.main()
