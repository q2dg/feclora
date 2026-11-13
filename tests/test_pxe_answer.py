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
            "repository_id": "nas-images",
            "target": {"wwn": "0x5000abcd1234", "serial": None},
            "confirm_destructive": True,
            "start": True,
        }

    def test_accepts_valid_answer(self):
        result = validate_pxe_answer(self.valid_answer())
        self.assertEqual(result["image_id"], "fedora-workstation")
        self.assertEqual(result["target"]["wwn"], "0x5000abcd1234")

    def test_accepts_valid_repository_ids(self):
        for identifier in ("nas", "archive-01", "s3-images"):
            with self.subTest(identifier=identifier):
                answer = self.valid_answer()
                answer["repository_id"] = identifier
                validate_pxe_answer(answer)

    def test_rejects_invalid_repository_ids(self):
        for identifier in ("", "../nas", "NAS", "nas/images", "a" * 49):
            with self.subTest(identifier=identifier):
                answer = self.valid_answer()
                answer["repository_id"] = identifier
                with self.assertRaises(PXEAnswerError):
                    validate_pxe_answer(answer)

    def test_rejects_legacy_repository_url_field(self):
        answer = self.valid_answer()
        answer["repository_url"] = "nfs://images.example.net/export"
        with self.assertRaises(PXEAnswerError):
            validate_pxe_answer(answer)

    def test_requires_stable_target_selector(self):(self):
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

    def test_rejects_credential_reference(self):
        answer = self.valid_answer()
        answer["credential_ref"] = "archive"
        with self.assertRaisesRegex(PXEAnswerError, "unknown fields"):
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
