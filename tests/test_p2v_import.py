import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from feclora.storage.p2v_import import P2VImportError, import_p2v_qcow2


class P2VImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name)
        self.qcow2 = self.repo / "physical.qcow2"
        self.qcow2.write_bytes(b"verified-qcow2")
        self.metadata = {
            "schema_version": 1, "image_id": "physical", "format": "qcow2",
            "source_device": "/dev/sda", "virtual_size_bytes": 4096,
            "file_size_bytes": self.qcow2.stat().st_size,
            "qcow2_sha256": hashlib.sha256(self.qcow2.read_bytes()).hexdigest(),
            "verified": True, "bootability_note": "Requires VM validation.",
        }
        (self.repo / "physical.p2v.json").write_text(json.dumps(self.metadata))

    def tearDown(self):
        self.directory.cleanup()

    def runner(self, argv, **kwargs):
        if argv[1] == "check":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[1:3] == ["info", "--output=json"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"format": "qcow2", "virtual-size": 4096}),
                stderr="",
            )
        if argv[1] == "convert":
            Path(argv[-1]).write_bytes(b"R" * 4096)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(argv)

    def test_imports_qcow2_as_native_manifest_backed_raw_disk_image(self):
        manifest = import_p2v_qcow2(
            self.repo, "physical", "physical-imported",
            qemu_img="/usr/bin/qemu-img", runner=self.runner,
        )
        self.assertEqual(manifest.image_type, "disk")
        self.assertEqual(manifest.partition_table, "unknown")
        self.assertEqual(manifest.source_size_bytes, 4096)
        self.assertEqual([item.role for item in manifest.artifacts], ["disk-image", "partition-table"])
        disk = self.repo / "physical-imported.disk.raw"
        self.assertEqual(disk.stat().st_size, 4096)
        committed = json.loads((self.repo / "physical-imported.manifest.json").read_text())
        self.assertEqual(committed["image_id"], "physical-imported")
        self.assertTrue((self.repo / "physical.qcow2").exists())
        self.assertTrue((self.repo / "physical.p2v.json").exists())

    def test_rejects_sidecar_digest_mismatch(self):
        self.metadata["qcow2_sha256"] = "0" * 64
        (self.repo / "physical.p2v.json").write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(P2VImportError, "does not match"):
            import_p2v_qcow2(self.repo, "physical", "imported", runner=self.runner)

    def test_rejects_virtual_capacity_mismatch(self):
        def wrong_size(argv, **kwargs):
            if argv[1] == "check":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[1:3] == ["info", "--output=json"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    "format": "qcow2", "virtual-size": 8192,
                }), stderr="")
            raise AssertionError(argv)
        with self.assertRaisesRegex(P2VImportError, "disagrees"):
            import_p2v_qcow2(self.repo, "physical", "imported", runner=wrong_size)

    def test_never_overwrites_existing_native_image(self):
        (self.repo / "imported.disk.raw").write_bytes(b"keep")
        with self.assertRaisesRegex(P2VImportError, "already exists"):
            import_p2v_qcow2(self.repo, "physical", "imported", runner=self.runner)
        self.assertEqual((self.repo / "imported.disk.raw").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
