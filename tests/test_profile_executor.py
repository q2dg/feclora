import json
import os
import tempfile
import unittest
from pathlib import Path

from feclora.storage.profile_executor import _consume_profile_once
from feclora.storage.restore_profile import RestoreProfileError


class ProfileConsumptionLedgerTests(unittest.TestCase):
    def test_consumption_is_durable_and_replay_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "logs" / "consumed.jsonl"
            _consume_profile_once("profile-123", ledger)
            event = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(event, {"profile_id": "profile-123", "status": "consumed"})
            with self.assertRaisesRegex(RestoreProfileError, "already been consumed"):
                _consume_profile_once("profile-123", ledger)

    def test_corrupt_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "consumed.jsonl"
            ledger.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(RestoreProfileError, "corrupt"):
                _consume_profile_once("profile-456", ledger)

    def test_symlink_ledger_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real.jsonl"
            link = Path(directory) / "ledger.jsonl"
            real.write_text("", encoding="utf-8")
            link.symlink_to(real)
            with self.assertRaises(RestoreProfileError):
                _consume_profile_once("profile-789", link)


if __name__ == "__main__":
    unittest.main()
