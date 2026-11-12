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

    def test_remote_clone_accepts_partition_target_only(self):
        payload = valid_job(
            operation="clone", image_id=None, source_device="/dev/nvme0n1p2",
            target_type="partition", transport="unicast",
            authorized_clients=["52:54:00:12:34:56"],
        )
        job = DeploymentJob.from_dict(payload)
        self.assertEqual(job.target_type, "partition")
        self.assertEqual(DeploymentJob.from_json(job.to_json()).target_type, "partition")

    def test_logical_volume_is_supported_for_save_and_restore_but_not_clone(self):
        for operation in ("save", "restore"):
            job = DeploymentJob.from_dict(valid_job(operation=operation, target_type="logical_volume"))
            self.assertEqual(job.target_type, "logical_volume")
            self.assertEqual(DeploymentJob.from_json(job.to_json()).target_type, "logical_volume")
        payload = valid_job(operation="clone", target_type="logical_volume")
        payload["image_id"] = None
        payload["source_device"] = "/dev/sda"
        with self.assertRaisesRegex(JobValidationError, "only for save or restore"):
            DeploymentJob.from_dict(payload)

    def test_clone_job_requires_local_source_device_and_has_no_image(self):
        payload = valid_job(
            operation="clone", image_id=None, source_device="/dev/nvme0n1",
            transport="unicast",
        )
        job = DeploymentJob.from_dict(payload)
        self.assertEqual(job.operation, "clone")
        self.assertIsNone(job.image_id)
        self.assertEqual(job.source_device, "/dev/nvme0n1")
        self.assertEqual(DeploymentJob.from_json(job.to_json()), job)
        for invalid_source in ("../sda", "/dev/", "/dev/sda\\n"):
            with self.subTest(source_device=invalid_source):
                with self.assertRaisesRegex(JobValidationError, "source_device"):
                    DeploymentJob.from_dict(valid_job(
                        operation="clone", image_id=None, source_device=invalid_source,
                    ))
        with self.assertRaisesRegex(JobValidationError, "image_id"):
            DeploymentJob.from_dict(valid_job(
                operation="clone", image_id="unexpected-image", source_device="/dev/sda",
            ))
        with self.assertRaisesRegex(JobValidationError, "unicast"):
            DeploymentJob.from_dict(valid_job(
                operation="clone", image_id=None, source_device="/dev/sda",
                transport="multicast", multicast_group="239.10.10.10", multicast_port=5000,
            ))

    def test_restore_job_can_reference_a_simple_remote_repository_id(self):
        job = DeploymentJob.from_dict(valid_job(repository_id="nas-images"))
        self.assertEqual(job.repository_id, "nas-images")
        self.assertEqual(DeploymentJob.from_json(job.to_json()), job)
        self.assertEqual(job.to_dict()["repository_id"], "nas-images")

    def test_per_client_stable_target_bindings_round_trip_and_match(self):
        payload = valid_job(
            authorized_clients=["52:54:00:12:34:56"],
            target_bindings={
                "52:54:00:12:34:56": {"wwn": "0x5000CCA123456789", "serial": "DISK-001"},
            },
        )
        job = DeploymentJob.from_dict(payload)
        self.assertEqual(
            DeploymentJob.from_json(job.to_json()).target_bindings,
            (("52:54:00:12:34:56", "0x5000CCA123456789", "DISK-001"),),
        )
        self.assertTrue(job.authorizes_target("52:54:00:12:34:56", {
            "wwn": "0x5000cca123456789", "serial": "DISK-001",
        }))
        self.assertFalse(job.authorizes_target("52:54:00:12:34:56", {
            "wwn": "0x5000cca123456789", "serial": "DISK-002",
        }))
        self.assertFalse(job.authorizes_target("52:54:00:12:34:56", {
            "wwn": "0x5000cca123456789",
        }))
        self.assertFalse(job.authorizes_target("52:54:00:12:34:57", {
            "wwn": "0x5000cca123456789", "serial": "DISK-001",
        }))

    def test_stable_target_bindings_must_cover_every_selected_client(self):
        with self.assertRaisesRegex(JobValidationError, "every selected Client"):
            DeploymentJob.from_dict(valid_job(target_bindings={
                "52:54:00:12:34:56": {"wwn": "wwn-1", "serial": None},
            }))

    def test_stable_target_bindings_require_whole_disk_targets(self):
        with self.assertRaisesRegex(JobValidationError, "whole-disk"):
            DeploymentJob.from_dict(valid_job(
                authorized_clients=["52:54:00:12:34:56"],
                target_type="partition",
                target_bindings={"52:54:00:12:34:56": {"wwn": "wwn-1", "serial": None}},
            ))

    def test_unbound_client_retains_interactive_target_approval(self):
        job = DeploymentJob.from_dict(valid_job())
        self.assertTrue(job.authorizes_target("52:54:00:12:34:56", {"path": "/dev/sda"}))

    def test_target_bindings_reject_unknown_clients_and_weak_selectors(self):
        invalid = [
            {"ff:54:00:12:34:56": {"wwn": "x", "serial": None}},
            {"52:54:00:12:34:99": {"wwn": "x", "serial": None}},
            {"52:54:00:12:34:56": {"wwn": None, "serial": None}},
            {"52:54:00:12:34:56": {"wwn": "", "serial": None}},
            {"52:54:00:12:34:56": {"wwn": "../device", "serial": None, "path": "/dev/sda"}},
            {"52:54:00:12:34:56": {"wwn": None, "serial": "bad" + chr(10) + "serial"}},
        ]
        for bindings in invalid:
            with self.subTest(bindings=bindings):
                with self.assertRaises(JobValidationError):
                    DeploymentJob.from_dict(valid_job(target_bindings=bindings))

    def test_repository_id_is_allowed_for_capture_and_restore_but_not_clone(self):
        capture = DeploymentJob.from_dict(valid_job(operation="save", repository_id="s3-archive"))
        self.assertEqual(capture.repository_id, "s3-archive")
        restore = DeploymentJob.from_dict(valid_job(repository_id="nas-images"))
        self.assertEqual(restore.repository_id, "nas-images")
        with self.assertRaisesRegex(JobValidationError, "only for save or restore"):
            DeploymentJob.from_dict(valid_job(
                operation="clone", image_id=None, source_device="/dev/sda",
                repository_id="s3-archive",
            ))
        for invalid in ("../images", "", "UpperCase"):
            with self.subTest(repository_id=invalid):
                with self.assertRaisesRegex(JobValidationError, "repository_id"):
                    DeploymentJob.from_dict(valid_job(repository_id=invalid))

    def test_non_clone_jobs_reject_source_device(self):
        with self.assertRaisesRegex(JobValidationError, "only valid for clone"):
            DeploymentJob.from_dict(valid_job(source_device="/dev/sda"))

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
