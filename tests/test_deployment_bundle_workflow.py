import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feclora.storage.image_manifest import ImageManifest


SCRIPT = Path(__file__).resolve().parents[1] / "build" / "create-deployment-bundle.py"
SPEC = importlib.util.spec_from_file_location("feclora_bundle_workflow", SCRIPT)
WORKFLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW)


def _job(image_id="fleet-image"):
    return {
        "schema_version": 1,
        "job_id": "00000000-0000-4000-8000-000000000030",
        "operation": "restore",
        "image_id": image_id,
        "target_type": "disk",
        "authorized_clients": ["02:00:00:00:00:01", "02:00:00:00:00:02"],
        "network_interface": "enp2s0",
        "transport": "multicast",
        "multicast_group": "239.10.10.10",
        "multicast_port": 9000,
        "start_policy": "automatic",
        "repository_id": "primary",
        "target_bindings": {
            "02:00:00:00:00:01": {"wwn": "naa.00000001", "serial": "disk-1"},
            "02:00:00:00:00:02": {"wwn": "naa.00000002", "serial": "disk-2"},
        },
        "confirm_destructive": True,
    }


def _write_image(repository):
    import hashlib
    disk = b"D" * 4096
    table = b"# partition table metadata\n"
    (repository / "fleet-image.disk.raw").write_bytes(disk)
    (repository / "fleet-image.sfdisk").write_bytes(table)
    manifest = ImageManifest.from_dict({
        "schema_version": 1, "image_id": "fleet-image", "image_type": "disk",
        "source_size_bytes": 4096, "logical_sector_size": 512,
        "partition_table": "unknown",
        "artifacts": [
            {"filename": "fleet-image.disk.raw", "role": "disk-image", "format": "raw",
             "compression": "none", "size_bytes": len(disk), "sha256": hashlib.sha256(disk).hexdigest()},
            {"filename": "fleet-image.sfdisk", "role": "partition-table", "format": "raw",
             "compression": "none", "size_bytes": len(table), "sha256": hashlib.sha256(table).hexdigest()},
        ],
    })
    (repository / "fleet-image.manifest.json").write_text(manifest.to_json(), encoding="utf-8")


class CoordinatedBundleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.fedora_iso = self.root / "fedora.iso"
        self.fedora_iso.write_bytes(b"installer")
        self.answer = self.root / "answer.json"
        self.answer.write_text(json.dumps(_job()), encoding="utf-8")
        self.output = self.root / "fleet-bundle"
        _write_image(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, argv, **kwargs):
        result_dir = Path(kwargs["env"]["FECLORA_RESULT_DIR"])
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "feclora-live.iso").write_bytes(b"built-live-iso")
        return SimpleNamespace(returncode=0)

    def test_builds_live_iso_and_publishes_one_shared_answer_bundle(self):
        captured = {}
        def fake_builder(iso, image_directory, manifest_path, answer_path, output_directory):
            captured["iso"] = Path(iso).read_bytes()
            captured["answer"] = Path(answer_path).read_text(encoding="utf-8")
            captured["manifest"] = ImageManifest.from_json(Path(manifest_path).read_text())
            captured["output"] = output_directory
            return {"published": True, "bundle_id": _job()["job_id"]}

        with patch.object(WORKFLOW, "build_deployment_bundle", side_effect=fake_builder) as builder:
            result = WORKFLOW.create_bundle(
                fedora_iso=str(self.fedora_iso), repository=str(self.repository),
                repository_id="primary", image_id="fleet-image",
                answer_file=str(self.answer), output_directory=str(self.output),
                runner=self.runner,
            )
        self.assertTrue(result["published"])
        self.assertTrue(result["iso_built"])
        self.assertFalse(result["image_captured"])
        self.assertEqual(captured["iso"], b"built-live-iso")
        self.assertEqual(json.loads(captured["answer"]), _job())
        self.assertEqual(captured["manifest"].image_id, "fleet-image")
        self.assertEqual(captured["output"], str(self.output))
        builder.assert_called_once()

    def test_rejects_answer_for_a_different_image_before_building_iso(self):
        self.answer.write_text(json.dumps(_job("another-image")), encoding="utf-8")
        runner = Mock()
        with self.assertRaisesRegex(WORKFLOW.BundleWorkflowError, "repository and image"):
            WORKFLOW.create_bundle(
                fedora_iso=str(self.fedora_iso), repository=str(self.repository),
                repository_id="primary", image_id="fleet-image",
                answer_file=str(self.answer), output_directory=str(self.output),
                runner=runner,
            )
        runner.assert_not_called()

    def test_can_capture_physical_source_before_iso_and_bundle_generation(self):
        self.repository.joinpath("fleet-image.manifest.json").unlink()
        self.repository.joinpath("fleet-image.disk.raw").unlink()
        self.repository.joinpath("fleet-image.sfdisk").unlink()
        with patch("feclora.storage.disk_capture.capture_disk", side_effect=lambda source, image_id, repo, **kwargs: _write_image(Path(repo))):
            with patch.object(WORKFLOW, "build_deployment_bundle", return_value={"published": True}):
                result = WORKFLOW.create_bundle(
                    fedora_iso=str(self.fedora_iso), repository=str(self.repository),
                    repository_id="primary", image_id="fleet-image",
                    answer_file=str(self.answer), output_directory=str(self.output),
                    capture_source="/dev/sdz", runner=self.runner,
                )
        self.assertTrue(result["image_captured"])


if __name__ == "__main__":
    unittest.main()
