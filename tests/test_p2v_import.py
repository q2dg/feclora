import hashlib
import json
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
            "logical_sector_size": 4096,
            "file_size_bytes": self.qcow2.stat().st_size,
            "qcow2_sha256": hashlib.sha256(self.qcow2.read_bytes()).hexdigest(),
            "verified": True, "bootability_note": "Requires VM validation.",
        }
        (self.repo / "physical.p2v.json").write_text(json.dumps(self.metadata))

    def tearDown(self):
        self.directory.cleanup()

    def runner(self, argv, **kwargs):
        if argv[0] == "/usr/bin/losetup" and argv[1:2] == ["--find"]:
            return SimpleNamespace(returncode=0, stdout="/dev/loop0\n", stderr="")
        if argv[0] == "/usr/bin/losetup" and argv[1:2] == ["--detach"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[0] == "/usr/sbin/sfdisk" and argv[1:2] == ["--dump"]:
            return SimpleNamespace(
                returncode=0,
                stdout="label: gpt\nunit: sectors\nsector-size: 4096\n\n/dev/loop0p1 : start=0, size=1, type=Linux filesystem\n",
                stderr="",
            )
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
            qemu_img="/usr/bin/qemu-img", losetup="/usr/bin/losetup", sfdisk="/usr/sbin/sfdisk", runner=self.runner,
        )
        self.assertEqual(manifest.image_type, "disk")
        self.assertEqual(manifest.partition_table, "gpt")
        self.assertEqual(manifest.source_size_bytes, 4096)
        self.assertEqual(manifest.logical_sector_size, 4096)
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
        with self.assertRaisesRegex(P2VImportError, "SHA-256 verification"):
            import_p2v_qcow2(self.repo, "physical", "imported", qemu_img="/usr/bin/qemu-img", losetup="/usr/bin/losetup", sfdisk="/usr/sbin/sfdisk", runner=self.runner)

    def test_rejects_virtual_capacity_mismatch(self):
        def wrong_size(argv, **kwargs):
            if argv[1] == "check":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[1:3] == ["info", "--output=json"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    "format": "qcow2", "virtual-size": 8192,
                }), stderr="")
            raise AssertionError(argv)
        with self.assertRaisesRegex(P2VImportError, "disagree"):
            import_p2v_qcow2(self.repo, "physical", "imported", qemu_img="/usr/bin/qemu-img", losetup="/usr/bin/losetup", sfdisk="/usr/sbin/sfdisk", runner=wrong_size)

    def test_rejects_boolean_qcow2_virtual_size(self):
        self.metadata["virtual_size_bytes"] = 1
        (self.repo / "physical.p2v.json").write_text(json.dumps(self.metadata))
        def boolean_size(argv, **kwargs):
            if argv[1] == "check":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[1:3] == ["info", "--output=json"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    "format": "qcow2", "virtual-size": True,
                }), stderr="")
            raise AssertionError(argv)
        with self.assertRaisesRegex(P2VImportError, "disagree"):
            import_p2v_qcow2(
                self.repo, "physical", "imported", qemu_img="/usr/bin/qemu-img",
                losetup="/usr/bin/losetup", sfdisk="/usr/sbin/sfdisk", runner=boolean_size,
            )


    def test_rejects_non_integer_logical_sector_size(self):
        self.metadata["logical_sector_size"] = 512.0
        (self.repo / "physical.p2v.json").write_text(json.dumps(self.metadata))
        with self.assertRaisesRegex(P2VImportError, "logical sector size"):
            import_p2v_qcow2(self.repo, "physical", "imported", runner=self.runner)

    def test_rejects_qcow2_with_external_backing_file(self):
        def backed_image(argv, **kwargs):
            if argv[1] == "check":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if argv[1:3] == ["info", "--output=json"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    "format": "qcow2", "virtual-size": 4096,
                    "backing-filename": "untrusted-base.qcow2",
                }), stderr="")
            raise AssertionError(argv)
        with self.assertRaisesRegex(P2VImportError, "dependencies"):
            import_p2v_qcow2(self.repo, "physical", "imported", qemu_img="/usr/bin/qemu-img", losetup="/usr/bin/losetup", sfdisk="/usr/sbin/sfdisk", runner=backed_image)

    def test_never_overwrites_existing_native_image(self):
        (self.repo / "imported.disk.raw").write_bytes(b"keep")
        with self.assertRaisesRegex(P2VImportError, "already exists"):
            import_p2v_qcow2(self.repo, "physical", "imported", runner=self.runner)
        self.assertEqual((self.repo / "imported.disk.raw").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
