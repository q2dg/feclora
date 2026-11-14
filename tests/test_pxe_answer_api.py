from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import MagicMock, patch

from feclora.webapi import WebAPIError, _publish_pxe_answer, _provide_pxe_age_passphrase, _read_pxe_answer_source


class PXEAnswerAPITests(unittest.TestCase):
    JOB_ID = "3b241101-e2bb-4255-8caf-4136c566a962"

    def answer(self) -> bytes:
        return json.dumps({
            "schema_version": 2,
            "operation": "restore",
            "image_id": "fedora",
            "repository_id": "nas-images",
            "target": {"wwn": "0x5000abcd", "serial": None},
            "confirm_destructive": True,
            "start": True,
        }).encode("utf-8")

    def test_rejects_invalid_base64_before_touching_pxe_services(self):
        with self.assertRaisesRegex(WebAPIError, "valid base64"):
            _publish_pxe_answer({
                "job_id": self.JOB_ID,
                "source": "upload",
                "answer_base64": "%%%not-base64%%%",
            })

    def test_upload_source_is_bounded_and_decoded(self):
        raw = self.answer()
        result = _read_pxe_answer_source({
            "job_id": self.JOB_ID, "source": "upload",
            "answer_base64": base64.b64encode(raw).decode("ascii"),
        })
        self.assertEqual(result, raw)

    def test_http_source_downloads_without_redirects_and_checks_size(self):
        raw = self.answer()
        response = MagicMock()
        response.status = 200
        response.headers = {"Content-Length": str(len(raw))}
        response.read.return_value = raw
        response.__enter__.return_value = response
        with patch("urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.return_value = response
            result = _read_pxe_answer_source({
                "job_id": self.JOB_ID, "source": "url",
                "url": "https://answers.example.test/restore.json",
            })
        self.assertEqual(result, raw)
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://answers.example.test/restore.json")

    def test_http_source_rejects_credentials_and_non_http_schemes(self):
        for url in ("file:///etc/passwd", "https://user:secret@example.test/answer.json",
                    "https://example.test/answer.json#fragment"):
            with self.subTest(url=url), self.assertRaises(WebAPIError):
                _read_pxe_answer_source({
                    "job_id": self.JOB_ID, "source": "url", "url": url,
                })

    def test_repository_source_reads_only_bounded_relative_regular_files(self):
        import os
        import tempfile
        from pathlib import Path

        class FakeS3Manager:
            def list(self):
                return []
        class FakeRemoteManager:
            def __init__(self, root):
                self.root = root
            def acquire_usage_lock(self, _identifier):
                return os.open(os.devnull, os.O_RDONLY)
            def resolve(self, _identifier):
                return str(self.root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.answer()
            (root / "answers").mkdir()
            (root / "answers" / "restore.json").write_bytes(raw)
            with patch("feclora.storage.s3_repository_manager.S3RepositoryManager",
                       return_value=FakeS3Manager()), \
                 patch("feclora.webapi._remote_repository_manager",
                       return_value=FakeRemoteManager(root)):
                result = _read_pxe_answer_source({
                    "job_id": self.JOB_ID, "source": "repository",
                    "repository_id": "nas-images",
                    "source_path": "answers/restore.json",
                })
            self.assertEqual(result, raw)

    def test_repository_source_rejects_parent_path_components(self):
        with self.assertRaisesRegex(WebAPIError, "safe relative path"):
            _read_pxe_answer_source({
                "job_id": self.JOB_ID, "source": "repository",
                "repository_id": "nas-images", "source_path": "../answer.json",
            })

    def test_age_passphrase_requires_a_nonempty_single_line_secret(self):
        with self.assertRaisesRegex(WebAPIError, "1-1024 UTF-8 bytes"):
            _provide_pxe_age_passphrase({"passphrase": "bad\nsecret"})
        with self.assertRaisesRegex(WebAPIError, "requires exactly passphrase"):
            _provide_pxe_age_passphrase({"passphrase": "secret", "job_id": self.JOB_ID})

    def test_rejects_unknown_or_missing_request_fields(self):
        with self.assertRaisesRegex(WebAPIError, "requires job_id"):
            _publish_pxe_answer({
                "job_id": self.JOB_ID,
                "source": "upload",
                "answer_base64": base64.b64encode(self.answer()).decode("ascii"),
                "signature_base64": "unused",
            })


if __name__ == "__main__":
    unittest.main()
