import base64
import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feclora.deployment.control import LocalTargetApproval
from feclora.deployment.job import DeploymentJob
from feclora.deployment.multicast_runtime import (
    MulticastDeploymentError, execute_multicast_restore,
    rendezvous_group_for, udpcast_config_for_job,
)
from feclora.storage.image_manifest import ImageArtifact
from feclora.storage.image_security import ImageSecurityError


def multicast_job(**changes):
    payload = {
        "schema_version": 1,
        "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "operation": "restore",
        "image_id": "golden-image",
        "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
        "network_interface": "enp1s0",
        "transport": "multicast",
        "multicast_group": "239.10.10.1",
        "multicast_port": 9000,
        "start_policy": "manual",
        "expected_clients": None,
        "start_deadline": None,
    }
    payload.update(changes)
    return DeploymentJob.from_dict(payload)


class MulticastRuntimeTests(unittest.TestCase):
    def test_rendezvous_group_is_deterministic_and_distinct(self):
        self.assertEqual(rendezvous_group_for("239.10.10.1"), "239.10.10.2")
        self.assertEqual(rendezvous_group_for("239.255.255.255"), "239.255.255.254")

    def test_udpcast_config_matches_multi_client_job(self):
        config = udpcast_config_for_job(multicast_job(), min_receivers=2)
        self.assertEqual(config.interface, "enp1s0")
        self.assertEqual(config.data_group, "239.10.10.1")
        self.assertEqual(config.rendezvous_group, "239.10.10.2")
        self.assertEqual(config.min_receivers, 2)

    def test_client_can_override_server_interface_with_its_local_interface(self):
        config = udpcast_config_for_job(
            multicast_job(), min_receivers=2, network_interface="ens192",
        )
        self.assertEqual(config.interface, "ens192")

    def test_udpcast_config_rejects_unicast_job(self):
        payload = multicast_job().to_dict()
        payload["transport"] = "unicast"
        payload["multicast_group"] = None
        payload["multicast_port"] = None
        job = DeploymentJob.from_dict(payload)
        with self.assertRaisesRegex(MulticastDeploymentError, "not configured"):
            udpcast_config_for_job(job, min_receivers=1)

    def test_client_verifies_manifest_and_staged_artifact_before_restore(self):
        job = multicast_job()
        approval = LocalTargetApproval(
            "/dev/feclora-test", "Disposable test disk",
            "ERASE /dev/feclora-test FROM URI:feclora-server",
        )
        artifact = ImageArtifact(
            "golden-image.raw", "disk-image", "raw", "none", 3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            encryption="age",
        )
        manifest = SimpleNamespace(image_id="golden-image", image_type="disk", artifacts=(artifact,))
        offer = {
            "type": "transfer_offer",
            "job_id": job.job_id,
            "image_id": job.image_id,
            "manifest_b64": base64.b64encode(b"{}").decode("ascii"),
            "signature_b64": base64.b64encode(b"signature").decode("ascii"),
        }
        tls = Mock()
        with tempfile.TemporaryDirectory() as repository:
            real_lstat = os.lstat
            def fake_lstat(path, *args, **kwargs):
                if path == approval.device_path:
                    return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
                return real_lstat(path, *args, **kwargs)
            def fake_receive(staging_directory, _artifact, _config, **_kwargs):
                private = tempfile.mkdtemp(prefix=".feclora-udpcast-", dir=staging_directory)
                path = os.path.join(private, "payload")
                with open(path, "wb") as stream:
                    stream.write(b"abc")
                return path
            with (
                patch("feclora.deployment.multicast_runtime.os.stat", side_effect=fake_lstat),
                patch("feclora.deployment.multicast_runtime.receive_control_message", return_value=offer),
                patch("feclora.deployment.multicast_runtime.verify_manifest_signature"),
                patch("feclora.deployment.multicast_runtime.ImageManifest.from_json", return_value=manifest),
                patch("feclora.deployment.multicast_runtime.receive_multicast_artifact_to_staging", side_effect=fake_receive),
                patch("feclora.deployment.multicast_runtime.verify_staged_multicast_artifact"),
                patch("feclora.deployment.multicast_runtime.restore_disk") as restore,
            ):
                result = execute_multicast_restore(
                    job, tls, approval,
                    server_identity="URI:feclora-server",
                    repository=repository,
                    trusted_server_public_key="/pki/server.pub",
                    firewall=Mock(),
                    network_interface="enp1s0", age_identity_file="/pki/client.age",
                )
            self.assertTrue(result[0])
            restore.assert_called_once()
            self.assertEqual(restore.call_args.args[0].endswith(".manifest.json"), True)
            self.assertEqual(restore.call_args.args[2], approval.device_path)
            self.assertTrue(tls.settimeout.called)

    def test_multicast_luks2_container_partition_dispatches_to_verified_partition_restore(self):
        job = multicast_job(target_type="partition")
        approval = LocalTargetApproval(
            "/dev/feclora-test-partition", "Disposable test partition",
            "ERASE /dev/feclora-test-partition FROM URI:feclora-server",
        )
        artifact = ImageArtifact(
            "golden-image_sda1.img", "partition-image", "raw", "none", 3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            partition_id="sda1", encryption="age",
        )
        manifest = SimpleNamespace(image_id="golden-image", image_type="partition", artifacts=(artifact,))
        offer = {
            "type": "transfer_offer", "job_id": job.job_id, "image_id": job.image_id,
            "manifest_b64": base64.b64encode(b"{}").decode("ascii"),
            "signature_b64": base64.b64encode(b"signature").decode("ascii"),
        }
        tls = Mock()
        with tempfile.TemporaryDirectory() as repository:
            real_lstat = os.lstat
            def fake_lstat(path, **kwargs):
                if path == approval.device_path and not kwargs:
                    return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
                return real_lstat(path, **kwargs)
            def fake_receive(staging_directory, _artifact, _config, **_kwargs):
                private = tempfile.mkdtemp(prefix=".feclora-udpcast-", dir=staging_directory)
                path = os.path.join(private, "payload")
                with open(path, "wb") as stream:
                    stream.write(b"abc")
                return path
            with (
                patch("feclora.deployment.multicast_runtime.os.lstat", side_effect=fake_lstat),
                patch("feclora.deployment.multicast_runtime.receive_control_message", return_value=offer),
                patch("feclora.deployment.multicast_runtime.verify_manifest_signature"),
                patch("feclora.deployment.multicast_runtime.ImageManifest.from_json", return_value=manifest),
                patch("feclora.deployment.multicast_runtime.receive_multicast_artifact_to_staging", side_effect=fake_receive),
                patch("feclora.deployment.multicast_runtime.verify_staged_multicast_artifact"),
                patch("feclora.deployment.multicast_runtime.restore_partition") as restore_partition,
                patch("feclora.deployment.multicast_runtime.restore_disk") as restore_disk,
            ):
                result = execute_multicast_restore(
                    job, tls, approval, server_identity="URI:feclora-server",
                    repository=repository, trusted_server_public_key="/pki/server.pub",
                    firewall=Mock(), network_interface="enp1s0", age_identity_file="/pki/client.age",
                )
            self.assertTrue(result[0])
            restore_partition.assert_called_once()
            restore_disk.assert_not_called()

    def test_logical_volume_manifest_dispatches_to_lv_restore_with_fresh_inventory(self):
        job = multicast_job(target_type="logical_volume")
        approval = LocalTargetApproval(
            "/dev/vg0/lv-data", "Disposable logical volume",
            "ERASE /dev/vg0/lv-data FROM URI:feclora-server",
        )
        artifact = ImageArtifact(
            "golden-image.raw", "logical-volume-image", "raw", "none", 3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        manifest = SimpleNamespace(
            image_id="golden-image", image_type="logical_volume", artifacts=(artifact,),
        )
        offer = {
            "type": "transfer_offer", "job_id": job.job_id, "image_id": job.image_id,
            "manifest_b64": base64.b64encode(b"{}").decode("ascii"),
            "signature_b64": base64.b64encode(b"signature").decode("ascii"),
        }
        tls = Mock()
        with tempfile.TemporaryDirectory() as repository:
            real_lstat = os.lstat
            def fake_lstat(path, *args, **kwargs):
                if path == approval.device_path:
                    return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
                return real_lstat(path, *args, **kwargs)
            def fake_receive(staging_directory, _artifact, _config, **_kwargs):
                private = tempfile.mkdtemp(prefix=".feclora-udpcast-", dir=staging_directory)
                staged = os.path.join(private, "payload")
                with open(staged, "wb") as stream:
                    stream.write(b"abc")
                return staged
            with (
                patch("feclora.deployment.multicast_runtime.os.lstat", side_effect=fake_lstat),
                patch("feclora.deployment.multicast_runtime.receive_control_message", return_value=offer),
                patch("feclora.deployment.multicast_runtime.verify_manifest_signature"),
                patch("feclora.deployment.multicast_runtime.ImageManifest.from_json", return_value=manifest),
                patch("feclora.deployment.multicast_runtime.receive_multicast_artifact_to_staging", side_effect=fake_receive),
                patch("feclora.deployment.multicast_runtime.verify_staged_multicast_artifact"),
                patch("feclora.deployment.multicast_runtime.restore_logical_volume") as restore_lv,
                patch("feclora.deployment.multicast_runtime.collect_inventory") as inventory,
            ):
                result = execute_multicast_restore(
                    job, tls, approval, server_identity="URI:feclora-server",
                    repository=repository, trusted_server_public_key="/pki/server.pub",
                    firewall=Mock(), network_interface="enp1s0",
                )
            self.assertTrue(result[0])
            restore_lv.assert_called_once()
            self.assertEqual(restore_lv.call_args.args[2], approval.device_path)
            self.assertEqual(
                restore_lv.call_args.kwargs["confirmation"],
                "ERASE /dev/vg0/lv-data",
            )
            self.assertIs(
                restore_lv.call_args.kwargs["inventory_provider"],
                inventory,
            )

    def test_invalid_signed_manifest_never_reaches_restore(self):
        job = multicast_job()
        approval = LocalTargetApproval(
            "/dev/feclora-test", "Disposable test disk",
            "ERASE /dev/feclora-test FROM URI:feclora-server",
        )
        offer = {
            "type": "transfer_offer",
            "job_id": job.job_id,
            "image_id": job.image_id,
            "manifest_b64": base64.b64encode(b"{}").decode("ascii"),
            "signature_b64": base64.b64encode(b"bad-signature").decode("ascii"),
        }
        with tempfile.TemporaryDirectory() as repository:
            real_lstat = os.lstat
            def fake_lstat(path, **kwargs):
                if path == approval.device_path and not kwargs:
                    return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
                return real_lstat(path, **kwargs)
            with (
                patch("feclora.deployment.multicast_runtime.os.lstat", side_effect=fake_lstat),
                patch("feclora.deployment.multicast_runtime.receive_control_message", return_value=offer),
                patch("feclora.deployment.multicast_runtime.verify_manifest_signature",
                      side_effect=ImageSecurityError("bad signature")),
                patch("feclora.deployment.multicast_runtime.restore_disk") as restore,
            ):
                with self.assertRaisesRegex(MulticastDeploymentError, "bad signature"):
                    execute_multicast_restore(
                        job, Mock(), approval,
                        server_identity="URI:feclora-server",
                        repository=repository,
                        trusted_server_public_key="/pki/server.pub",
                        firewall=Mock(),
                        network_interface="enp1s0",
                    )
            restore.assert_not_called()

    def test_client_rejects_wrong_local_confirmation_before_receiving(self):
        job = multicast_job()
        approval = LocalTargetApproval(
            "/dev/feclora-test", "Disposable test disk", "ERASE /dev/other FROM URI:feclora-server",
        )
        with tempfile.TemporaryDirectory() as repository:
            with patch("feclora.deployment.multicast_runtime.os.lstat") as lstat:
                lstat.return_value = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
                with self.assertRaisesRegex(MulticastDeploymentError, "confirmation"):
                    execute_multicast_restore(
                        job, Mock(), approval,
                        server_identity="URI:feclora-server",
                        repository=repository,
                        trusted_server_public_key="/pki/server.pub",
                        firewall=Mock(),
                        network_interface="enp1s0",
                    )


if __name__ == "__main__":
    unittest.main()
