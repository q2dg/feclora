from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from feclora.storage.deployment_bundle import DeploymentBundleError, build_deployment_bundle


class DeploymentBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.iso = self.root / "feclora-live.iso"
        self.iso.write_bytes(b"generic live iso")
        self.xorriso = self.root / "xorriso"
        self.xorriso.write_text("#!/bin/sh\nexit 0\n")
        self.xorriso.chmod(0o755)
        self.images = self.root / "images"
        self.images.mkdir()
        self.disk = self.images / "disk.raw"
        self.disk.write_bytes(b"disk bytes")
        self.table = self.images / "ptable.bin"
        self.table.write_bytes(b"gpt")
        self.manifest = self.root / "image-manifest.json"
        self.write_manifest()
        self.answer = self.root / "answer.json"
        self.write_answer()
        self.output = self.root / "bundle"

    def write_manifest(self):
        artifacts = []
        for path, role in ((self.disk, "disk-image"), (self.table, "partition-table")):
            raw = path.read_bytes()
            artifacts.append({
                "filename": path.name, "role": role, "format": "raw",
                "compression": "none", "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "image_id": "fleet-image",
            "image_type": "disk", "source_size_bytes": 1024 * 1024,
            "logical_sector_size": 512, "partition_table": "gpt",
            "artifacts": artifacts,
        }))

    def write_answer(self, image_id="fleet-image", clients=None):
        clients = clients or ["02:00:00:00:00:01", "02:00:00:00:00:02"]
        bindings = {
            mac: {"wwn": f"naa.{index:08d}", "serial": f"disk-{index}"}
            for index, mac in enumerate(clients, start=1)
        }
        self.answer.write_text(json.dumps({
            "schema_version": 1, "job_id": str(uuid.uuid4()),
            "operation": "restore", "image_id": image_id, "target_type": "disk",
            "authorized_clients": clients, "network_interface": "enp2s0",
            "transport": "multicast", "multicast_group": "239.10.10.10",
            "multicast_port": 9000, "start_policy": "automatic",
            "repository_id": "primary", "target_bindings": bindings,
            "confirm_destructive": True,
        }))

    def runner(self, argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout="El Torito boot catalog\n", stderr="")

    def build(self, **overrides):
        args = {
            "base_iso": str(self.iso), "image_directory": str(self.images),
            "manifest_path": str(self.manifest), "answer_path": str(self.answer),
            "output_directory": str(self.output), "xorriso": str(self.xorriso),
            "runner": self.runner, "free_bytes": lambda _path: 10**9,
            "source_revision": "a" * 40,
        }
        args.update(overrides)
        return build_deployment_bundle(**args)

    def test_builds_atomic_bundle_with_one_canonical_shared_answer(self):
        result = self.build()
        self.assertTrue(result["published"])
        self.assertEqual(result["client_count"], 2)
        self.assertEqual((self.output / "feclora-live.iso").read_bytes(), self.iso.read_bytes())
        answer = (self.output / "answer.json").read_text()
        from feclora.deployment.job import DeploymentJob
        expected_answer = DeploymentJob.from_dict(json.loads(self.answer.read_text())).to_json() + "\n"
        self.assertEqual(answer, expected_answer)
        bundle = json.loads((self.output / "bundle-manifest.json").read_text())
        self.assertEqual(bundle["files"]["images/disk.raw"]["path"], "images/disk.raw")
        self.assertEqual(bundle["files"]["feclora-live.iso"]["path"], "feclora-live.iso")
        self.assertEqual(bundle["authorized_clients"], ["02:00:00:00:00:01", "02:00:00:00:00:02"])
        self.assertEqual(set(path.name for path in self.output.iterdir()), {
            "images", "feclora-live.iso", "image-manifest.json", "answer.json", "bundle-manifest.json"
        })

    def test_rejects_image_reference_mismatch_before_publication(self):
        self.write_answer(image_id="different-image")
        with self.assertRaisesRegex(DeploymentBundleError, "answer must be"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_missing_client_target_binding(self):
        value = json.loads(self.answer.read_text())
        value["target_bindings"].pop("02:00:00:00:00:02")
        self.answer.write_text(json.dumps(value))
        with self.assertRaises(DeploymentBundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_corrupt_image_artifact(self):
        self.disk.write_bytes(b"corrupt")
        with self.assertRaisesRegex(DeploymentBundleError, "mismatch"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_existing_bundle_without_overwrite(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_text("preserve")
        with self.assertRaisesRegex(DeploymentBundleError, "already exists"):
            self.build()
        self.assertEqual(marker.read_text(), "preserve")

    def test_rejects_single_client_multicast(self):
        self.write_answer(clients=["02:00:00:00:00:01"])
        with self.assertRaisesRegex(DeploymentBundleError, "at least two"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_non_bootable_iso_report(self):
        def runner(argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout="not bootable", stderr="")
        with self.assertRaisesRegex(DeploymentBundleError, "El Torito"):
            self.build(runner=runner)
        self.assertFalse(self.output.exists())


    def test_copy_interruption_never_publishes_partial_bundle_and_cleans_staging(self):
        from feclora.storage import deployment_bundle

        real_copy = deployment_bundle._copy_verified

        def interrupted_copy(source, destination, expected_size, expected_digest):
            if destination.name == "disk.raw":
                raise OSError("simulated artifact-copy interruption")
            return real_copy(source, destination, expected_size, expected_digest)

        with patch("feclora.storage.deployment_bundle._copy_verified", side_effect=interrupted_copy):
            with self.assertRaisesRegex(DeploymentBundleError, "publication failed"):
                self.build()

        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / ".bundle.publish.lock").exists())
        self.assertEqual(
            sorted(path.name for path in self.root.glob(".bundle.staging-*")),
            [],
        )

    def test_atomic_publish_failure_cleans_complete_staging_without_visible_output(self):

        def fail_final_rename(staging, output):
            self.assertTrue((staging / "images" / "disk.raw").is_file())
            self.assertTrue((staging / "image-manifest.json").is_file())
            self.assertTrue((staging / "answer.json").is_file())
            bundle_manifest = staging / "bundle-manifest.json"
            self.assertTrue(bundle_manifest.is_file())
            metadata = json.loads(bundle_manifest.read_text())
            self.assertIn("images/disk.raw", metadata["files"])
            raise OSError("simulated interruption before atomic directory rename")

        with patch("feclora.storage.deployment_bundle._rename_noreplace", side_effect=fail_final_rename):
            with self.assertRaisesRegex(DeploymentBundleError, "publication failed"):
                self.build()

        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / ".bundle.publish.lock").exists())
        self.assertEqual(list(self.root.glob(".bundle.staging-*")), [])


if __name__ == "__main__":
    unittest.main()
