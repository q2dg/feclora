from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from feclora.storage.recovery_boot import (
    RecoveryBootError, _load_answer, discover_payload,
)


class RecoveryBootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / "FECLORA" / "RECOVERY"
        self.payload.mkdir(parents=True)

    def write_answer(self, **overrides):
        value = {
            "schema_version": 1,
            "operation": "restore",
            "image_id": "rescue-01",
            "target": {"wwn": "naa.12345678", "serial": None},
            "confirm_destructive": True,
            "start": True,
        }
        value.update(overrides)
        (self.payload / "answer.json").write_text(json.dumps(value), encoding="utf-8")

    def test_discovery_finds_single_recovery_payload(self):
        self.assertEqual(discover_payload((self.root,)), self.payload)

    def test_discovery_returns_none_without_payload(self):
        self.assertIsNone(discover_payload((self.root / "missing",)))

    def test_discovery_rejects_multiple_recovery_payloads(self):
        other = self.root / "other"
        (other / "FECLORA" / "RECOVERY").mkdir(parents=True)
        with self.assertRaisesRegex(RecoveryBootError, "multiple"):
            discover_payload((self.root, other))

    def test_valid_answer_requires_stable_target_identity(self):
        self.write_answer()
        answer = _load_answer(self.payload)
        self.assertEqual(answer["image_id"], "rescue-01")
        self.assertEqual(answer["selector"].wwn, "naa.12345678")

    def test_answer_rejects_unknown_fields(self):
        self.write_answer(repository_id="remote")
        with self.assertRaisesRegex(RecoveryBootError, "unknown fields"):
            _load_answer(self.payload)

    def test_answer_rejects_missing_destructive_authorization(self):
        self.write_answer(confirm_destructive=False)
        with self.assertRaisesRegex(RecoveryBootError, "explicitly authorize"):
            _load_answer(self.payload)

    def test_answer_rejects_duplicate_json_keys(self):
        (self.payload / "answer.json").write_text(
            '{"schema_version":1,"schema_version":1}', encoding="utf-8"
        )
        with self.assertRaisesRegex(RecoveryBootError, "duplicate"):
            _load_answer(self.payload)

    def test_answer_rejects_symlink(self):
        target = self.root / "outside.json"
        target.write_text("{}", encoding="utf-8")
        (self.payload / "answer.json").symlink_to(target)
        with self.assertRaisesRegex(RecoveryBootError, "non-symlink"):
            _load_answer(self.payload)


if __name__ == "__main__":
    unittest.main()
