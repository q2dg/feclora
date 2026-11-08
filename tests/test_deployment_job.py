import json
import unittest

from feclora.deployment.job import DeploymentJob, JobValidationError


def valid_job(**changes):
    payload = {
        "schema_version": 1,
        "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "operation": "restore",
        "image_id": "golden-image-2026",
        "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
        "network_interface": "enp1s0",
        "transport": "unicast",
        "multicast_group": None,
        "multicast_port": None,
        "start_policy": "manual",
        "expected_clients": None,
        "start_deadline": None,
    }
    payload.update(changes)
    return payload


class DeploymentJobTests(unittest.TestCase):
    def test_parses_and_normalizes_authorized_clients(self):
        job = DeploymentJob.from_dict(valid_job(authorized_clients=["52:54:00:12:34:AB"]))
        self.assertEqual(job.authorized_clients, ("52:54:00:12:34:ab",))
        self.assertTrue(job.authorizes_client("52:54:00:12:34:AB"))
        self.assertFalse(job.authorizes_client("52:54:00:12:34:AC"))

    def test_json_round_trip_is_canonical(self):
        job = DeploymentJob.from_dict(valid_job())
        decoded = DeploymentJob.from_json(job.to_json())
        self.assertEqual(decoded, job)
        self.assertEqual(json.loads(job.to_json())["schema_version"], 1)

    def test_partition_target_type_is_preserved_and_validated(self):
        job = DeploymentJob.from_dict(valid_job(target_type="partition", transport="multicast", multicast_group="239.10.10.10", multicast_port=5000))
        self.assertEqual(job.target_type, "partition")
        self.assertEqual(DeploymentJob.from_json(job.to_json()).target_type, "partition")
        with self.assertRaisesRegex(JobValidationError, "target_type"):
            DeploymentJob.from_dict(valid_job(target_type="volume"))
        with self.assertRaisesRegex(JobValidationError, "whole disks"):
            DeploymentJob.from_dict(valid_job(operation="save", target_type="partition"))

    def test_rejects_unknown_fields(self):
        with self.assertRaisesRegex(JobValidationError, "Unknown"):
            DeploymentJob.from_dict(valid_job(shell_command="dd if=/dev/zero"))

    def test_rejects_invalid_job_id_and_image_path(self):
        with self.assertRaisesRegex(JobValidationError, "UUID"):
            DeploymentJob.from_dict(valid_job(job_id="not-a-uuid"))
        with self.assertRaisesRegex(JobValidationError, "simple identifier"):
            DeploymentJob.from_dict(valid_job(image_id="../etc/passwd"))

    def test_rejects_empty_or_duplicate_client_allowlist(self):
        with self.assertRaisesRegex(JobValidationError, "non-empty"):
            DeploymentJob.from_dict(valid_job(authorized_clients=[]))
        with self.assertRaisesRegex(JobValidationError, "Duplicate"):
            DeploymentJob.from_dict(valid_job(authorized_clients=[
                "52:54:00:12:34:56", "52:54:00:12:34:56"
            ]))

    def test_rejects_non_unicast_client_mac(self):
        with self.assertRaisesRegex(JobValidationError, "unicast"):
            DeploymentJob.from_dict(valid_job(authorized_clients=["ff:ff:ff:ff:ff:ff"]))
        with self.assertRaisesRegex(JobValidationError, "unicast"):
            DeploymentJob.from_dict(valid_job(authorized_clients=["00:00:00:00:00:00"]))

    def test_rejects_wrong_json_field_types(self):
        with self.assertRaisesRegex(JobValidationError, "schema_version"):
            DeploymentJob.from_dict(valid_job(schema_version=True))
        with self.assertRaisesRegex(JobValidationError, "operation"):
            DeploymentJob.from_dict(valid_job(operation=[]))
        with self.assertRaisesRegex(JobValidationError, "multicast_group"):
            DeploymentJob.from_dict(valid_job(
                transport="multicast", multicast_group=[], multicast_port=5000
            ))

    def test_rejects_invalid_interface_name(self):
        with self.assertRaisesRegex(JobValidationError, "interface"):
            DeploymentJob.from_dict(valid_job(network_interface="../../tmp/x"))

    def test_multicast_requires_multicast_group_and_valid_port(self):
        payload = valid_job(
            transport="multicast",
            multicast_group="239.10.10.10",
            multicast_port=5000,
        )
        self.assertEqual(DeploymentJob.from_dict(payload).multicast_group, "239.10.10.10")
        with self.assertRaisesRegex(JobValidationError, "administratively scoped"):
            DeploymentJob.from_dict(valid_job(
                transport="multicast", multicast_group="192.0.2.1", multicast_port=5000
            ))
        with self.assertRaisesRegex(JobValidationError, "multicast_port"):
            DeploymentJob.from_dict(valid_job(
                transport="multicast", multicast_group="239.10.10.10", multicast_port=80
            ))

    def test_multicast_portbase_must_be_even_and_within_udpcast_range(self):
        for port in (1023, 9001, 65535):
            with self.subTest(port=port):
                with self.assertRaisesRegex(JobValidationError, "even UDPcast"):
                    DeploymentJob.from_dict(valid_job(
                        transport="multicast",
                        multicast_group="239.10.10.10",
                        multicast_port=port,
                    ))

    def test_unicast_rejects_multicast_parameters(self):
        with self.assertRaisesRegex(JobValidationError, "only valid for multicast"):
            DeploymentJob.from_dict(valid_job(multicast_group="239.10.10.10"))

    def test_start_policies_are_mutually_exclusive(self):
        self.assertEqual(
            DeploymentJob.from_dict(valid_job(
                start_policy="expected_clients", expected_clients=2
            )).expected_clients,
            2,
        )
        self.assertTrue(DeploymentJob.from_dict(valid_job(
            start_policy="deadline", start_deadline="2030-01-01T12:00:00Z"
        )).start_deadline.endswith("Z"))
        with self.assertRaisesRegex(JobValidationError, "expected_clients"):
            DeploymentJob.from_dict(valid_job(
                start_policy="expected_clients", expected_clients=3
            ))
        with self.assertRaisesRegex(JobValidationError, "UTC"):
            DeploymentJob.from_dict(valid_job(
                start_policy="deadline", start_deadline="2030-01-01T12:00:00"
            ))

    def test_rejects_invalid_json_and_unsupported_schema(self):
        with self.assertRaisesRegex(JobValidationError, "valid JSON"):
            DeploymentJob.from_json("{")
        with self.assertRaisesRegex(JobValidationError, "schema_version"):
            DeploymentJob.from_dict(valid_job(schema_version=2))


if __name__ == "__main__":
    unittest.main()
