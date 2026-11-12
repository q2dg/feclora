from __future__ import annotations

import json
import unittest

from feclora.network.pxe_answer import (
    PXEAnswerError, parse_pxe_answer, validate_pxe_answer,
)


class PXEAnswerTests(unittest.TestCase):
    def valid_answer(self):
        return {
            "schema_version": 1,
            "operation": "restore",
            "image_id": "fedora-workstation",
            "repository_url": "sftp://images.example.net/feclora",
            "target": {"wwn": "0x5000abcd1234", "serial": None},
            "confirm_destructive": True,
            "start": True,
        }

    def test_accepts_valid_sftp_answer(self):
        result = validate_pxe_answer(self.valid_answer())
        self.assertEqual(result["image_id"], "fedora-workstation")
        self.assertEqual(result["target"]["wwn"], "0x5000abcd1234")

    def test_accepts_declared_repository_url_schemes(self):
        for url in (
            "sshfs://images.example.net/feclora",
            "smb://images.example.net/images",
            "nfs://images.example.net/export/feclora",
            "webdav://images.example.net/feclora",
            "webdavs://images.example.net/feclora",
            "https://images.example.net/feclora",
            "s3://bucket.example.net/feclora",
        ):
            with self.subTest(url=url):
                answer = self.valid_answer()
                answer["repository_url"] = url
                validate_pxe_answer(answer)

    def test_rejects_removed_peer_to_peer_schemes(self):
        for url in (
            "bittorrent://tracker.example.net/feclora",
            "magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
        ):
            with self.subTest(url=url):
                answer = self.valid_answer()
                answer["repository_url"] = url
                with self.assertRaises(PXEAnswerError):
                    validate_pxe_answer(answer)

    def test_rejects_embedded_repository_credentials(self):
        answer = self.valid_answer()
        answer["repository_url"] = "sftp://operator:secret@images.example.net/images"
        with self.assertRaises(PXEAnswerError):
            validate_pxe_answer(answer)

    def test_requires_stable_target_selector(self):
        answer = self.valid_answer()
        answer["target"] = {"wwn": None, "serial": None}
        with self.assertRaises(PXEAnswerError):
            validate_pxe_answer(answer)

    def test_requires_explicit_destructive_confirmation_and_start(self):
        for field in ("confirm_destructive", "start"):
            answer = self.valid_answer()
            answer[field] = False
            with self.subTest(field=field), self.assertRaises(PXEAnswerError):
                validate_pxe_answer(answer)

    def test_rejects_unknown_and_missing_fields(self):
        answer = self.valid_answer()
        answer["device_path"] = "/dev/sda"
        with self.assertRaises(PXEAnswerError):
            validate_pxe_answer(answer)
        answer = self.valid_answer()
        del answer["image_id"]
        with self.assertRaises(PXEAnswerError):
            validate_pxe_answer(answer)

    def test_rejects_duplicate_json_fields(self):
        raw = json.dumps(self.valid_answer())
        raw = raw[:-1] + ',"start":false}'
        with self.assertRaises(PXEAnswerError):
            parse_pxe_answer(raw)

    def test_rejects_invalid_json_and_oversized_document(self):
        with self.assertRaises(PXEAnswerError):
            parse_pxe_answer("{")
        with self.assertRaises(PXEAnswerError):
            parse_pxe_answer(b"x" * (64 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
