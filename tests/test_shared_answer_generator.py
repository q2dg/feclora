import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "build" / "generate-shared-answer.py"
SPEC = importlib.util.spec_from_file_location("feclora_shared_answer_generator", SCRIPT)
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


CLIENTS = [
    "02:00:00:00:00:01=naa.0001|disk-1",
    "02:00:00:00:00:02=|disk-2",
]


class SharedAnswerGeneratorTests(unittest.TestCase):
    def test_generates_one_canonical_shared_multicast_answer(self):
        document = GENERATOR.build_shared_answer(
            image_id="fleet-image", repository_id="primary",
            clients=CLIENTS, network_interface="enp2s0",
            job_id="00000000-0000-4000-8000-000000000030",
        )
        answer = json.loads(document)
        self.assertEqual(answer["authorized_clients"], [
            "02:00:00:00:00:01", "02:00:00:00:00:02",
        ])
        self.assertEqual(answer["target_bindings"]["02:00:00:00:00:02"],
                         {"wwn": None, "serial": "disk-2"})
        self.assertEqual(answer["transport"], "multicast")
        self.assertEqual(answer["start_policy"], "automatic")
        self.assertTrue(answer["confirm_destructive"])
        self.assertNotIn("client_answers", answer)

    def test_pxe_changes_only_boot_transport_interface(self):
        answer = json.loads(GENERATOR.build_shared_answer(
            image_id="fleet-image", repository_id="primary",
            clients=CLIENTS, network_interface="ignored0", boot_method="pxe",
        ))
        self.assertEqual(answer["network_interface"], "auto")
        self.assertEqual(answer["boot_method"], "pxe")

    def test_unicast_omits_multicast_configuration(self):
        answer = json.loads(GENERATOR.build_shared_answer(
            image_id="fleet-image", repository_id="primary",
            clients=[CLIENTS[0]], network_interface="enp2s0",
            transport="unicast",
        ))
        self.assertIsNone(answer["multicast_group"])
        self.assertIsNone(answer["multicast_port"])

    def test_rejects_single_client_multicast_and_incomplete_bindings(self):
        with self.assertRaisesRegex(GENERATOR.AnswerGenerationError, "at least two"):
            GENERATOR.build_shared_answer(
                image_id="fleet-image", repository_id="primary",
                clients=[CLIENTS[0]], network_interface="enp2s0",
            )
        with self.assertRaisesRegex(GENERATOR.AnswerGenerationError, "requires a WWN"):
            GENERATOR.build_shared_answer(
                image_id="fleet-image", repository_id="primary",
                clients=["02:00:00:00:00:01=|"], network_interface="enp2s0",
                transport="unicast",
            )

    def test_output_is_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "answer.json"
            document = GENERATOR.build_shared_answer(
                image_id="fleet-image", repository_id="primary",
                clients=CLIENTS, network_interface="enp2s0",
            )
            GENERATOR.write_shared_answer(document, str(output))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(GENERATOR.AnswerGenerationError, "already exists"):
                GENERATOR.write_shared_answer("replacement", str(output))
            self.assertEqual(output.read_text(), document)


if __name__ == "__main__":
    unittest.main()
