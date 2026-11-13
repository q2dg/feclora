import json
import unittest

from feclora.storage.gpt_inspection import GPTInspectionError, parse_sfdisk_gpt_json


class SfdiskGPTParserTests(unittest.TestCase):
    def payload(self, **overrides):
        table = {
            "label": "gpt",
            "unit": "sectors",
            "sectorsize": 512,
            "firstlba": 34,
            "lastlba": 1048542,
            "partitions": [
                {
                    "node": "/dev/sda1",
                    "start": 2048,
                    "size": 102400,
                    "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                    "uuid": "11111111-2222-3333-4444-555555555555",
                    "name": "EFI System",
                    "attrs": "RequiredPartition,NoBlockIOProtocol",
                },
                {
                    "node": "/dev/sda2",
                    "start": 104448,
                    "size": 204800,
                    "type": "0fc63daf-8483-4772-8e79-3d69d8477de4",
                },
            ],
        }
        table.update(overrides)
        return json.dumps({"partitiontable": table})

    def test_parses_gpt_partition_records(self):
        result = parse_sfdisk_gpt_json(
            self.payload(), disk_path="/dev/sda", expected_sector_size=512
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["node"], "/dev/sda1")
        self.assertEqual(result[0]["start"], 2048)
        self.assertEqual(result[0]["name"], "EFI System")
        self.assertEqual(result[0]["attrs"], "RequiredPartition,NoBlockIOProtocol")
        self.assertEqual(result[1]["size"], 204800)

    def test_rejects_non_gpt_and_non_sector_units(self):
        with self.assertRaisesRegex(GPTInspectionError, "only GPT"):
            parse_sfdisk_gpt_json(
                self.payload(label="dos"), disk_path="/dev/sda", expected_sector_size=512
            )
        with self.assertRaisesRegex(GPTInspectionError, "units must be sectors"):
            parse_sfdisk_gpt_json(
                self.payload(unit="bytes"), disk_path="/dev/sda", expected_sector_size=512
            )

    def test_rejects_sector_size_mismatch(self):
        with self.assertRaisesRegex(GPTInspectionError, "does not match"):
            parse_sfdisk_gpt_json(
                self.payload(), disk_path="/dev/sda", expected_sector_size=4096
            )

    def test_rejects_foreign_duplicate_or_invalid_partition_nodes(self):
        for node in ("/dev/sdb1", "/dev/sdaa1", "/dev/sda1"):
            table = json.loads(self.payload())
            table["partitiontable"]["partitions"][1]["node"] = node
            with self.subTest(node=node):
                with self.assertRaises(GPTInspectionError):
                    parse_sfdisk_gpt_json(
                        json.dumps(table), disk_path="/dev/sda", expected_sector_size=512
                    )

    def test_rejects_overlapping_partitions_and_invalid_guids(self):
        table = json.loads(self.payload())
        table["partitiontable"]["partitions"][1]["start"] = 100000
        with self.assertRaisesRegex(GPTInspectionError, "overlap"):
            parse_sfdisk_gpt_json(
                json.dumps(table), disk_path="/dev/sda", expected_sector_size=512
            )
        table = json.loads(self.payload())
        table["partitiontable"]["partitions"][0]["type"] = "not-a-guid"
        with self.assertRaisesRegex(GPTInspectionError, "type GUID"):
            parse_sfdisk_gpt_json(
                json.dumps(table), disk_path="/dev/sda", expected_sector_size=512
            )

    def test_validates_gpt_usable_lba_bounds_against_disk_capacity(self):
        payload = json.loads(self.payload())
        payload["partitiontable"]["partitions"][0]["start"] = 33
        with self.assertRaisesRegex(GPTInspectionError, "before the GPT usable"):
            parse_sfdisk_gpt_json(
                json.dumps(payload), disk_path="/dev/sda",
                expected_sector_size=512, disk_size_bytes=536870912,
            )
        payload = json.loads(self.payload())
        payload["partitiontable"]["lastlba"] = 2_000_000
        with self.assertRaisesRegex(GPTInspectionError, "invalid GPT usable-LBA"):
            parse_sfdisk_gpt_json(
                json.dumps(payload), disk_path="/dev/sda",
                expected_sector_size=512, disk_size_bytes=536870912,
            )
        payload = json.loads(self.payload())
        payload["partitiontable"].pop("firstlba")
        with self.assertRaisesRegex(GPTInspectionError, "did not report GPT"):
            parse_sfdisk_gpt_json(
                json.dumps(payload), disk_path="/dev/sda",
                expected_sector_size=512, disk_size_bytes=536870912,
            )

    def test_rejects_invalid_gpt_partition_attributes(self):
        payload = json.loads(self.payload())
        payload["partitiontable"]["partitions"][0]["attrs"] = ["not", "a", "string"]
        with self.assertRaisesRegex(GPTInspectionError, "invalid GPT partition attributes"):
            parse_sfdisk_gpt_json(
                json.dumps(payload), disk_path="/dev/sda", expected_sector_size=512
            )

    def test_rejects_malformed_input_and_empty_partition_list(self):
        with self.assertRaisesRegex(GPTInspectionError, "invalid JSON"):
            parse_sfdisk_gpt_json("{", disk_path="/dev/sda", expected_sector_size=512)
        with self.assertRaisesRegex(GPTInspectionError, "no readable partitions"):
            parse_sfdisk_gpt_json(
                self.payload(partitions=[]), disk_path="/dev/sda", expected_sector_size=512
            )


from types import SimpleNamespace
from unittest.mock import Mock

from feclora.storage.gpt_inspection import inspect_gpt_source


class GPTSourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {
            "blockdevices": [{
                "path": "/dev/sda",
                "type": "disk",
                "size": 512 * 1024 * 1024,
                "log-sec": 512,
                "pttype": "gpt",
                "children": [
                    {"path": "/dev/sda1", "type": "part", "fstype": "vfat"},
                    {"path": "/dev/sda2", "type": "part", "fstype": "ext4"},
                ],
            }]
        }

    def make_runner(self, *, inventory=None, sfdisk=None, disk_size="536870912", sector="512"):
        outputs = [
            json.dumps(inventory if inventory is not None else self.inventory),
            disk_size,
            sector,
            sfdisk if sfdisk is not None else self.payload(),
        ]
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(stdout=outputs.pop(0), stderr="", returncode=0)

        return runner, calls

    def payload(self):
        return self_payload()

    def inspect(self, runner):
        return inspect_gpt_source(
            "/dev/sda",
            runner=runner,
            which=lambda name: "/usr/sbin/" + name,
            device_validator=lambda path: True,
            safety_check=lambda path: None,
            effective_uid=lambda: 0,
        )

    def test_discovers_geometry_partition_table_and_filesystems(self):
        runner, calls = self.make_runner()
        result = self.inspect(runner)
        self.assertEqual(result["source_size_bytes"], 536870912)
        self.assertEqual(result["sector_size"], 512)
        self.assertEqual(result["partition_table_type"], "gpt")
        self.assertEqual(result["filesystem_types"], {
            "/dev/sda1": "vfat", "/dev/sda2": "ext4"
        })
        self.assertEqual(len(result["partitions"]), 2)
        self.assertTrue(any("sfdisk" in arg for arg in calls[-1]))

    def test_refuses_partition_inventory_mismatch(self):
        inventory = self.inventory.copy()
        inventory["blockdevices"] = [dict(self.inventory["blockdevices"][0])]
        inventory["blockdevices"][0]["children"] = inventory["blockdevices"][0]["children"][:1]
        runner, _ = self.make_runner(inventory=inventory)
        with self.assertRaisesRegex(GPTInspectionError, "partition set"):
            self.inspect(runner)

    def test_refuses_lsblk_capacity_disagreement(self):
        inventory = json.loads(json.dumps(self.inventory))
        inventory["blockdevices"][0]["size"] += 512
        runner, _ = self.make_runner(inventory=inventory)
        with self.assertRaisesRegex(GPTInspectionError, "geometry disagree"):
            self.inspect(runner)

    def test_refuses_sector_geometry_disagreement(self):
        runner, _ = self.make_runner(sector="4096")
        with self.assertRaisesRegex(GPTInspectionError, "geometry disagree"):
            self.inspect(runner)

    def test_refuses_non_disk_and_safety_failure_before_commands(self):
        inventory = {"blockdevices": [{
            "path": "/dev/mapper/root", "type": "crypt", "log-sec": 512,
            "pttype": "gpt", "children": []
        }]}
        runner, calls = self.make_runner(inventory=inventory)
        with self.assertRaisesRegex(GPTInspectionError, "whole disk"):
            self.inspect(runner)
        self.assertEqual(len(calls), 1)

        runner, calls = self.make_runner()
        with self.assertRaisesRegex(GPTInspectionError, "offline and unused"):
            inspect_gpt_source(
                "/dev/sda", runner=runner, which=lambda name: "/usr/sbin/" + name,
                device_validator=lambda path: True,
                safety_check=lambda path: (_ for _ in ()).throw(RuntimeError("mounted")),
                effective_uid=lambda: 0,
            )
        self.assertEqual(calls, [])


def self_payload():
    return json.dumps({
        "partitiontable": {
            "label": "gpt", "unit": "sectors", "sectorsize": 512,
            "firstlba": 34, "lastlba": 1048542,
            "partitions": [
                {"node": "/dev/sda1", "start": 2048, "size": 102400,
                 "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
                {"node": "/dev/sda2", "start": 104448, "size": 204800,
                 "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"},
            ],
        }
    })

if __name__ == "__main__":
    unittest.main()
