from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from feclora.network.pxe_answer_client import (
    PXEAnswerClientError,
    fetch_live_pxe_answer,
)


JOB = "3b241101-e2bb-4255-8caf-4136c566a962"
URL = f"http://192.0.2.10:8080/answers/{JOB}/answer.json"


def answer() -> bytes:
    return json.dumps({
        "schema_version": 1,
        "operation": "restore",
        "image_id": "golden",
        "repository_url": "nfs://repo.example/images",
        "target": {"wwn": "0x5000c50012345678", "serial": None},
        "confirm_destructive": True,
        "start": True,
    }).encode("utf-8")


class PXEAnswerClientTests(unittest.TestCase):
    def test_interactive_boot_does_not_download_or_publish(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "answer.json"
            result = fetch_live_pxe_answer(
                "quiet feclora.pxe_mode=interactive",
                destination=destination,
                downloader=lambda _url: self.fail("interactive boot must not download"),
            )
            self.assertIsNone(result)
            self.assertFalse(destination.exists())

    def test_unattended_boot_downloads_validates_and_publishes_answer(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            seen = []
            result = fetch_live_pxe_answer(
                f"quiet feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
                f"feclora.pxe_answer_url={URL}",
                destination=destination,
                downloader=lambda url: (seen.append(url) or answer()),
            )
            self.assertEqual(seen, [URL])
            self.assertEqual(result["image_id"], "golden")
            self.assertEqual(destination.read_bytes(), answer())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)

    def test_invalid_download_is_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "pxe" / "answer.json"
            with self.assertRaises(PXEAnswerClientError):
                fetch_live_pxe_answer(
                    f"feclora.pxe_mode=unattended-answer feclora.pxe_job_id={JOB} "
                    f"feclora.pxe_answer_url={URL}",
                    destination=destination,
                    downloader=lambda _url: b'{"schema_version":1}',
                )
            self.assertFalse(destination.exists())

    def test_invalid_handoff_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PXEAnswerClientError):
                fetch_live_pxe_answer(
                    "feclora.pxe_mode=unattended-answer feclora.pxe_job_id=bad",
                    destination=Path(root) / "answer.json",
                    downloader=lambda _url: self.fail("invalid handoff must not download"),
                )


if __name__ == "__main__":
    unittest.main()
