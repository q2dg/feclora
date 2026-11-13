import json
import unittest
from types import SimpleNamespace

from feclora.storage.target_inspection import TargetInspectionError, inspect_restore_target


class RestoreTargetInspectionTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {"blockdevices": [{
            "path": "/dev/sdb", "type": "disk", "size": 1073741824,
            "log-sec": 512, "pttype": "gpt", "model": "Test disk",
            "serial": "SERIAL-1", "wwn": "wwn-test",
            "children": [
                {"path": "/dev/sdb1", "type": "part", "fstype": "vfat", "size": 104857600},
                {"path": "/dev/sdb2", "type": "part", "fstype": "ext4", "size": 943718400},
            ],
        }]}

    def make_runner(self, *, inventory=None, size="1073741824", sector="512"):
        outputs = [json.dumps(inventory if inventory is not None else self.inventory), size, sector]
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(stdout=outputs.pop(0), stderr="", returncode=0)

        return runner, calls

    def inspect(self, runner):
        return inspect_restore_target(
            "/dev/sdb", runner=runner, which=lambda name: "/usr/sbin/" + name,
            device_validator=lambda path: True, safety_check=lambda path: None,
            effective_uid=lambda: 0,
        )

    def test_reports_geometry_identity_and_existing_partitions_read_only(self):
        runner, calls = self.make_runner()
        result = self.inspect(runner)
        self.assertEqual(result["target_size_bytes"], 1073741824)
        self.assertEqual(result["sector_size"], 512)
        self.assertEqual(result["model"], "Test disk")
        self.assertEqual(len(result["existing_partitions"]), 2)
        self.assertFalse(result["write_authorized"])
        self.assertEqual(len(calls), 3)

    def test_refuses_geometry_disagreement(self):
        runner, _ = self.make_runner(size="1073741823")
        with self.assertRaisesRegex(TargetInspectionError, "geometry disagree"):
            self.inspect(runner)

    def test_refuses_unsupported_sector_size(self):
        inventory = json.loads(json.dumps(self.inventory))
        inventory["blockdevices"][0]["log-sec"] = 1024
        runner, _ = self.make_runner(inventory=inventory, sector="1024")
        with self.assertRaisesRegex(TargetInspectionError, "unsupported"):
            self.inspect(runner)

    def test_refuses_non_disk_and_unknown_child_layers(self):
        inventory = {"blockdevices": [{"path": "/dev/mapper/target",
            "type": "crypt", "size": 1024, "log-sec": 512, "children": []}]}
        runner, calls = self.make_runner(inventory=inventory)
        with self.assertRaisesRegex(TargetInspectionError, "whole disk"):
            self.inspect(runner)
        self.assertEqual(calls, [])

        inventory = json.loads(json.dumps(self.inventory))
        inventory["blockdevices"][0]["children"][0]["type"] = "crypt"
        runner, _ = self.make_runner(inventory=inventory)
        with self.assertRaisesRegex(TargetInspectionError, "unrecognized child"):
            self.inspect(runner)

    def test_refuses_safety_failure_before_inspection(self):
        runner, calls = self.make_runner()
        with self.assertRaisesRegex(TargetInspectionError, "offline and unused"):
            inspect_restore_target(
                "/dev/sdb", runner=runner, which=lambda name: "/usr/sbin/" + name,
                device_validator=lambda path: True,
                safety_check=lambda path: (_ for _ in ()).throw(RuntimeError("mounted")),
                effective_uid=lambda: 0,
            )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
