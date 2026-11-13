import json
import unittest

from feclora.storage.gpt_inspection import GPTInspectionError, parse_sfdisk_gpt_json


class SfdiskGPTParserTests(unittest.TestCase):
    def payload(self, **overrides):
        table = {
            "label": "gpt",
            "unit": "sectors",
            "sectorsize": 512,
            "partitions": [
                {
                    "node": "/dev/sda1",
                    "start": 2048,
                    "size": 102400,
                    "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                    "uuid": "11111111-2222-3333-4444-555555555555",
                    "name": "EFI System",
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

    def test_rejects_malformed_input_and_empty_partition_list(self):
        with self.assertRaisesRegex(GPTInspectionError, "invalid JSON"):
            parse_sfdisk_gpt_json("{", disk_path="/dev/sda", expected_sector_size=512)
        with self.assertRaisesRegex(GPTInspectionError, "no readable partitions"):
            parse_sfdisk_gpt_json(
                self.payload(partitions=[]), disk_path="/dev/sda", expected_sector_size=512
            )


if __name__ == "__main__":
    unittest.main()
