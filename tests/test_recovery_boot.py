from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

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


    def test_restore_engine_interruption_propagates_after_prewrite_revalidation(self):
        selector = object()
        manifest = SimpleNamespace(image_id="rescue-01", artifacts=[])
        observed = {}
        def interrupted_restore(*args, **kwargs):
            observed.update(kwargs)
            kwargs["pre_write_callback"]()
            raise RuntimeError("simulated power-loss boundary")
        with patch("feclora.storage.recovery_boot._load_answer",
                   return_value={"image_id": "rescue-01", "selector": selector}), \
             patch("feclora.storage.recovery_boot._load_manifest", return_value=manifest), \
             patch("feclora.storage.recovery_boot._resolve", return_value=("/dev/sda", {})), \
             patch("feclora.storage.recovery_boot.operation_record", return_value=nullcontext()), \
             patch("feclora.storage.recovery_boot.execute_restore", side_effect=interrupted_restore):
            with self.assertRaisesRegex(RuntimeError, "power-loss boundary"):
                from feclora.storage.recovery_boot import execute_recovery
                execute_recovery(self.payload)
        self.assertEqual(observed["target_type"], "disk")
        self.assertEqual(observed["confirmation"], "ERASE /dev/sda")
        self.assertTrue(callable(observed["pre_write_callback"]))

    def test_target_identity_drift_blocks_restore_before_engine_write(self):
        selector = object()
        manifest = SimpleNamespace(image_id="rescue-01", artifacts=[])
        writes = []
        def changed_target(*_args, **_kwargs):
            return "/dev/sdb", {}
        def attempted_restore(*args, **kwargs):
            kwargs["pre_write_callback"]()
            writes.append("write")
        with patch("feclora.storage.recovery_boot._load_answer",
                   return_value={"image_id": "rescue-01", "selector": selector}), \
             patch("feclora.storage.recovery_boot._load_manifest", return_value=manifest), \
             patch("feclora.storage.recovery_boot._resolve", side_effect=[
                 ("/dev/sda", {}), changed_target(None, None)
             ]), \
             patch("feclora.storage.recovery_boot.operation_record", return_value=nullcontext()), \
             patch("feclora.storage.recovery_boot.execute_restore", side_effect=attempted_restore):
            from feclora.storage.recovery_boot import execute_recovery
            with self.assertRaisesRegex(RecoveryBootError, "identity or device path changed"):
                execute_recovery(self.payload)
        self.assertEqual(writes, [])

    def test_discovery_finds_single_recovery_payload(self):
        with patch("feclora.storage.recovery_boot.os.path.ismount", return_value=True):
            self.assertEqual(discover_payload((self.root,)), self.payload)

    def test_discovery_ignores_payload_in_unmounted_directory(self):
        with patch("feclora.storage.recovery_boot.os.path.ismount", return_value=False):
            self.assertIsNone(discover_payload((self.root,)))

    def test_discovery_does_not_follow_symlinked_feclora_directory(self):
        media = self.root / "media"
        media.mkdir()
        outside = self.root / "outside"
        (outside / "RECOVERY").mkdir(parents=True)
        (media / "FECLORA").symlink_to(outside, target_is_directory=True)
        with patch("feclora.storage.recovery_boot.os.path.ismount", return_value=True):
            self.assertIsNone(discover_payload((media,)))

    def test_discovery_does_not_follow_symlinked_recovery_directory(self):
        media = self.root / "media"
        (media / "FECLORA").mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        (media / "FECLORA" / "RECOVERY").symlink_to(outside, target_is_directory=True)
        with patch("feclora.storage.recovery_boot.os.path.ismount", return_value=True):
            self.assertIsNone(discover_payload((media,)))

    def test_discovery_returns_none_without_payload(self):
        self.assertIsNone(discover_payload((self.root / "missing",)))

    def test_discovery_rejects_multiple_recovery_payloads(self):
        other = self.root / "other"
        (other / "FECLORA" / "RECOVERY").mkdir(parents=True)
        with patch("feclora.storage.recovery_boot.os.path.ismount", return_value=True):
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
