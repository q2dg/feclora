from __future__ import annotations

import base64
import json
import unittest

from feclora.webapi import WebAPIError, _publish_pxe_answer


class PXEAnswerAPITests(unittest.TestCase):
    JOB_ID = "3b241101-e2bb-4255-8caf-4136c566a962"

    def answer(self) -> bytes:
        return json.dumps({
            "schema_version": 1,
            "operation": "restore",
            "image_id": "fedora",
            "repository_url": "sftp://repo.example/images",
            "target": {"wwn": "0x5000abcd", "serial": None},
            "confirm_destructive": True,
            "start": True,
        }).encode("utf-8")

    def test_rejects_invalid_base64_before_touching_pxe_services(self):
        with self.assertRaisesRegex(WebAPIError, "valid base64"):
            _publish_pxe_answer({
                "job_id": self.JOB_ID,
                "answer_base64": "%%%not-base64%%%",
            })

    def test_rejects_unknown_or_missing_request_fields(self):
        with self.assertRaisesRegex(WebAPIError, "requires job_id"):
            _publish_pxe_answer({
                "job_id": self.JOB_ID,
                "answer_base64": base64.b64encode(self.answer()).decode("ascii"),
                "signature_base64": "unused",
            })


if __name__ == "__main__":
    unittest.main()
