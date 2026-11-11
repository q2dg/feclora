import gzip
import hashlib
import json
import os
import tempfile
import unittest
from io import BytesIO
from types import SimpleNamespace

from feclora.storage.logical_volume_restore import (
    LogicalVolumeRestoreError,
    restore_logical_volume,
)
from feclora.storage.image_manifest import ImageManifest
from feclora.storage.partition_restore import PartitionRestoreError


def manifest_dict(payload, *, image_type="logical_volume"):
    return {
        "schema_version": 1,
        "image_id": "root-lv",
        "image_type": image_type,
        "source_size_bytes": len(payload),
        "logical_sector_size": 512,
        "partition_table": "none",
        "artifacts": [{
            "filename": "root.img.gz",
            "role": "logical-volume-image" if image_type == "logical_volume" else "partition-image",
            "format": "raw",
            "compression": "gzip",
            "size_bytes": len(gzip.compress(payload, mtime=0)),
            "sha256": hashlib.sha256(gzip.compress(payload, mtime=0)).hexdigest(),
        }],
        "storage": {
            "schema_version": 1,
            "capture_scope": "logical_volume_bytes",
            "source_layer": "lvm_logical_volume",
            "lvm_vg_name": "source-vg",
            "lvm_vg_uuid": "source-vg-uuid",
            "lvm_lv_name": "root",
            "lvm_lv_uuid": "source-lv-uuid",
            "dependencies": [{
                "kind": "lvm_volume_group",
                "identity": "source-vg-uuid",
                "included_in_source_bytes": False,
            }],
        },
    }


def target_inventory(*, mounted=None, segment="linear", thin=False):
    return {
        "volume_topology": {"status": "available", "volume_groups": [{
            "name": "target-vg", "uuid": "target-vg-uuid", "status": "healthy",
            "missing_pv_count": 0, "pv_count_reported": 1,
            "pv_members": [{"path": "/dev/sda2", "uuid": "pv-1", "missing": False}],
            "logical_volumes": [{
                "path": "/dev/target/root", "name": "root", "uuid": "target-lv-uuid",
                "size_bytes": 20000, "major_minor": "253:4", "segment_type": segment,
                "thin_provisioned": thin, "pool": None, "snapshot": False,
                "origin": None, "hidden": False, "health": None,
            }],
        }]},
        "devices": [{
            "path": "/dev/target/root", "type": "lvm", "major_minor": "253:4",
            "logical_sector_size": 512, "read_only": False,
            "mountpoints": mounted or [], "children": [],
        }],
    }


class InputPipe:
    def __init__(self):
        self.data = bytearray()
    def write(self, chunk):
        self.data.extend(chunk)
        return len(chunk)
    def close(self):
        pass


class FakeProcess:
    def __init__(self, *, readback=None):
        self.returncode = 0
        self.stdin = InputPipe()
        self.stdout = BytesIO(readback) if readback is not None else None
    def wait(self):
        return self.returncode
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15


class LogicalVolumeRestoreExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = b"feclora-logical-volume-image" * 300
        stored = gzip.compress(self.payload, mtime=0)
        with open(os.path.join(self.temp.name, "root.img.gz"), "wb") as stream:
            stream.write(stored)
        with open(os.path.join(self.temp.name, "root.manifest.json"), "w", encoding="utf-8") as stream:
            json.dump(manifest_dict(self.payload), stream)
        self.calls = []
        self.written = bytearray()
        self.readback = self.payload

    def runner(self, command, **kwargs):
        if command[0] == "lsblk":
            return SimpleNamespace(stdout="20000 lvm 512 0\n", returncode=0)
        raise AssertionError(f"unexpected command: {command}")

    def factory(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == "dd" and any(arg.startswith("of=") for arg in argv):
            proc = FakeProcess()
            original_close = proc.stdin.close
            def close():
                self.written.extend(proc.stdin.data)
                original_close()
            proc.stdin.close = close
            return proc
        if argv[0] == "dd" and any(arg.startswith("if=") for arg in argv):
            return FakeProcess(readback=self.readback)
        raise AssertionError(f"unexpected writer command: {argv}")

    def restore(self, **kwargs):
        return restore_logical_volume(
            "root.manifest.json", self.temp.name, "/dev/target/root",
            confirmation="ERASE /dev/target/root",
            inventory=target_inventory(),
            executables={"lsblk": "lsblk", "dd": "dd"},
            runner=self.runner,
            device_validator=lambda _path: True,
            target_safety_check=lambda _path: None,
            effective_uid=lambda: 0,
            popen_factory=self.factory,
            **kwargs,
        )

    def test_raw_restore_writes_and_verifies_exact_bytes(self):
        manifest = self.restore()
        self.assertEqual(manifest.image_type, "logical_volume")
        self.assertEqual(bytes(self.written), self.payload)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("if=/dev/target/root", self.calls[1])

    def test_rejects_partition_manifest_before_writer(self):
        with open(os.path.join(self.temp.name, "root.manifest.json"), encoding="utf-8") as stream:
            value = json.load(stream)
        value["image_type"] = "partition"
        value["artifacts"][0]["role"] = "partition-image"
        value["artifacts"][0]["partition_id"] = "1"
        value.pop("storage", None)
        with open(os.path.join(self.temp.name, "root.manifest.json"), "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        with self.assertRaisesRegex(LogicalVolumeRestoreError, "requires a logical_volume image manifest"):
            self.restore()
        self.assertEqual(self.calls, [])

    def test_rejects_mounted_target_before_writer(self):
        with self.assertRaisesRegex(LogicalVolumeRestoreError, "mounted or in use"):
            restore_logical_volume(
                "root.manifest.json", self.temp.name, "/dev/target/root",
                confirmation="ERASE /dev/target/root", inventory=target_inventory(mounted=["/mnt/root"]),
                executables={"lsblk": "lsblk", "dd": "dd"}, runner=self.runner,
                device_validator=lambda _path: True, target_safety_check=lambda _path: None,
                effective_uid=lambda: 0, popen_factory=self.factory,
            )
        self.assertEqual(self.calls, [])

    def test_rejects_unsupported_segment_before_writer(self):
        with self.assertRaisesRegex(LogicalVolumeRestoreError, "segment type.*not supported"):
            restore_logical_volume(
                "root.manifest.json", self.temp.name, "/dev/target/root",
                confirmation="ERASE /dev/target/root",
                inventory=target_inventory(segment="raid1"),
                executables={"lsblk": "lsblk", "dd": "dd"}, runner=self.runner,
                device_validator=lambda _path: True, target_safety_check=lambda _path: None,
                effective_uid=lambda: 0, popen_factory=self.factory,
            )
        self.assertEqual(self.calls, [])

    def test_fails_when_readback_bytes_differ(self):
        self.readback = b"x" * len(self.payload)
        with self.assertRaisesRegex(PartitionRestoreError, "read-back verification failed"):
            self.restore()
        self.assertEqual(bytes(self.written), self.payload)

    def test_rechecks_lvm_inventory_immediately_before_write(self):
        calls = []
        def inventory_provider():
            calls.append(True)
            return target_inventory(mounted=["/mnt/root"]) if len(calls) > 1 else target_inventory()
        with self.assertRaisesRegex(LogicalVolumeRestoreError, "pre-write check failed.*mounted or in use"):
            restore_logical_volume(
                "root.manifest.json", self.temp.name, "/dev/target/root",
                confirmation="ERASE /dev/target/root", inventory_provider=inventory_provider,
                executables={"lsblk": "lsblk", "dd": "dd"}, runner=self.runner,
                device_validator=lambda _path: True, target_safety_check=lambda _path: None,
                effective_uid=lambda: 0, popen_factory=self.factory,
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.calls, [])
    def test_requires_exact_confirmation(self):
        with self.assertRaisesRegex(LogicalVolumeRestoreError, "explicit confirmation"):
            restore_logical_volume(
                "root.manifest.json", self.temp.name, "/dev/target/root",
                confirmation="yes", inventory=target_inventory(),
                device_validator=lambda _path: True,
            )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
