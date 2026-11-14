from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from feclora.storage.recovery_iso import RecoveryISOError, build_recovery_iso


class RecoveryISOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "feclora-live.iso"
        self.base.write_bytes(b"base iso bytes")
        self.images = self.root / "images"
        self.images.mkdir()
        self.artifact = self.images / "disk.raw"
        self.artifact.write_bytes(b"verified disk image bytes")
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "image_id": "rescue-01", "image_type": "disk",
            "source_size_bytes": len(self.artifact.read_bytes()),
            "logical_sector_size": 512, "partition_table": "gpt",
            "artifacts": [
                {"filename": "disk.raw", "role": "disk-image", "format": "raw",
                 "compression": "none", "size_bytes": self.artifact.stat().st_size,
                 "sha256": self.digest},
                {"filename": "ptable.bin", "role": "partition-table", "format": "raw",
                 "compression": "none", "size_bytes": 1, "sha256": "a" * 64}
            ]
        }))
        (self.images / "ptable.bin").write_bytes(b"x")
        # Update the table artifact digest to match the fixture bytes.
        value = json.loads(self.manifest.read_text())
        value["artifacts"][1]["sha256"] = hashlib.sha256(b"x").hexdigest()
        self.manifest.write_text(json.dumps(value))
        self.answer = self.root / "answer.json"
        self.answer.write_text(json.dumps({
            "schema_version": 1, "operation": "restore", "image_id": "rescue-01",
            "target": {"wwn": "naa.12345678", "serial": None},
            "confirm_destructive": True, "start": True
        }))
        self.output = self.root / "rescue.iso"
        self.xorriso = self.root / "xorriso"
        self.xorriso.write_text("#!/bin/sh\nexit 0\n")
        self.xorriso.chmod(0o755)

    def runner(self, commands):
        def run(argv, **kwargs):
            commands.append(argv)
            if "-outdev" in argv:
                Path(argv[argv.index("-outdev") + 1]).write_bytes(b"assembled iso")
            if "-find" in argv:
                return SimpleNamespace(returncode=0, stdout=(
                    "El Torito boot catalog\n/FECLORA/RECOVERY/disk.raw\n"
                    "/FECLORA/RECOVERY/ptable.bin\n/FECLORA/RECOVERY/manifest.json\n"
                    "/FECLORA/RECOVERY/answer.json\n"
                ), stderr="")
            return SimpleNamespace(returncode=0, stdout="El Torito boot catalog\n", stderr="")
        return run

    def build(self, **overrides):
        commands = []
        args = {
            "base_iso": str(self.base), "image_directory": str(self.images),
            "manifest_path": str(self.manifest), "answer_path": str(self.answer),
            "output_path": str(self.output), "xorriso": str(self.xorriso),
            "runner": self.runner(commands), "free_bytes": lambda _path: 10**12,
        }
        args.update(overrides)
        return build_recovery_iso(**args), commands

    def test_builds_new_iso_and_replays_boot_catalog(self):
        result, commands = self.build()
        self.assertTrue(result["verified"])
        self.assertTrue(result["boot_catalog_preserved"])
        self.assertEqual(self.output.read_bytes(), b"assembled iso")
        build_command = next(command for command in commands if "-outdev" in command)
        self.assertIn(["-boot_image", "any", "replay"], [
            build_command[index:index + 4] for index in range(len(build_command) - 3)
        ])
        self.assertEqual(self.base.read_bytes(), b"base iso bytes")

    def test_rejects_modified_artifact_before_running_xorriso(self):
        self.artifact.write_bytes(b"tampered")
        commands = []
        with self.assertRaisesRegex(RecoveryISOError, "SHA-256"):
            self.build(runner=self.runner(commands))
        self.assertEqual(commands, [])

    def test_rejects_answer_for_different_image(self):
        value = json.loads(self.answer.read_text())
        value["image_id"] = "other-image"
        self.answer.write_text(json.dumps(value))
        with self.assertRaisesRegex(RecoveryISOError, "selected restore image"):
            self.build()

    def test_rejects_unknown_answer_fields(self):
        value = json.loads(self.answer.read_text())
        value["repository_id"] = "external"
        self.answer.write_text(json.dumps(value))
        with self.assertRaisesRegex(RecoveryISOError, "unknown fields"):
            self.build()

    def test_rejects_existing_output_without_overwrite(self):
        self.output.write_bytes(b"keep me")
        with self.assertRaisesRegex(RecoveryISOError, "overwrite"):
            self.build()
        self.assertEqual(self.output.read_bytes(), b"keep me")

    def test_rejects_insufficient_output_capacity(self):
        with self.assertRaisesRegex(RecoveryISOError, "insufficient output capacity"):
            self.build(free_bytes=lambda _path: 1)

    def test_rejects_base_iso_without_el_torito(self):
        commands = []
        def run(argv, **kwargs):
            commands.append(argv)
            return SimpleNamespace(returncode=0, stdout="not bootable", stderr="")
        with self.assertRaisesRegex(RecoveryISOError, "El Torito"):
            self.build(runner=run)
        self.assertEqual(len(commands), 1)

    def test_rejects_symlinked_image_artifact(self):
        self.artifact.unlink()
        target = self.root / "outside.raw"
        target.write_bytes(b"verified disk image bytes")
        self.artifact.symlink_to(target)
        with self.assertRaisesRegex(RecoveryISOError, "non-symlink"):
            self.build()


if __name__ == "__main__":
    unittest.main()
