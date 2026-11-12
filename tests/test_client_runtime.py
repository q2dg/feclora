import json
import os
import stat
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.client_runtime import (
    ClientImageRuntimeError, execute_client_image_job,
)
from feclora.deployment.control import LocalTargetApproval
from feclora.deployment.job import DeploymentJob


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"


def make_job(operation, target_type="disk"):
    return DeploymentJob.from_dict({
        "schema_version": 1, "job_id": JOB_ID, "operation": operation,
        "image_id": "golden-image", "target_type": target_type, "authorized_clients": ["52:54:00:12:34:56"],
        "network_interface": "enp1s0", "transport": "unicast",
        "multicast_group": None, "multicast_port": None,
        "start_policy": "manual", "expected_clients": None, "start_deadline": None,
    })


def control_frame(message):
    encoded = json.dumps(message, separators=(",", ":")).encode("ascii")
    return struct.pack("!I", len(encoded)) + encoded


class FakeTLS:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.outgoing = bytearray()
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, count):
        result = bytes(self.incoming[:count])
        del self.incoming[:count]
        return result

    def sendall(self, data):
        self.outgoing.extend(data)


class ClientImageRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.approval = LocalTargetApproval(
            "/dev/vda", "Virtual disk 1",
            "ERASE /dev/vda",
        )
        self.block_device = SimpleNamespace(st_mode=stat.S_IFBLK)

    def test_restore_receives_signed_image_before_protected_disk_restore(self):
        tls = FakeTLS(control_frame({
            "type": "transfer_offer", "job_id": JOB_ID, "image_id": "golden-image",
        }))
        pre_write_check = lambda: None
        with patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device), \
             patch("feclora.deployment.client_runtime.os.path.isfile", return_value=True), \
             patch("feclora.deployment.client_runtime.receive_image_set", return_value="/repo/golden-image.manifest.json") as receive, \
             patch("feclora.deployment.client_runtime.restore_disk") as restore:
            result = execute_client_image_job(
                make_job("restore"), tls, self.approval,
                server_identity="URI:feclora-server", repository="/repo",
                trusted_server_public_key="/trusted/server.pub",
                transfer_progress_callback=lambda current, total: None,
                pre_write_callback=pre_write_check,
            )
        self.assertTrue(result[0])
        receive.assert_called_once()
        self.assertIsNotNone(receive.call_args.kwargs["progress_callback"])
        restore.assert_called_once()
        self.assertEqual(restore.call_args.args[0], "/repo/golden-image.manifest.json")
        self.assertTrue(restore.call_args.kwargs["require_signature"])
        self.assertEqual(restore.call_args.kwargs["confirmation"], "ERASE /dev/vda")
        self.assertIs(restore.call_args.kwargs["pre_write_callback"], pre_write_check)

    def test_logical_volume_restore_dispatches_to_local_lv_engine(self):
        tls = FakeTLS(control_frame({
            "type": "transfer_offer", "job_id": JOB_ID, "image_id": "golden-image",
        }))
        with (
            patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device),
            patch("feclora.deployment.client_runtime.receive_image_set", return_value="/repo/golden-image.manifest.json"),
            patch("feclora.deployment.client_runtime.restore_logical_volume") as restore,
        ):
            result = execute_client_image_job(
                make_job("restore", "logical_volume"), tls, self.approval,
                server_identity="URI:feclora-server", repository="/repo",
                trusted_server_public_key=None,
            )
        self.assertTrue(result[0])
        restore.assert_called_once()
        self.assertEqual(restore.call_args.args[2], "/dev/vda")
        self.assertEqual(restore.call_args.kwargs["confirmation"], "ERASE /dev/vda")
        self.assertTrue(callable(restore.call_args.kwargs["inventory_provider"]))

    def test_unsigned_restore_over_mtls_does_not_require_minisign(self):
        tls = FakeTLS(control_frame({
            "type": "transfer_offer", "job_id": JOB_ID, "image_id": "golden-image",
        }))
        with patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device), \
             patch("feclora.deployment.client_runtime.receive_image_set", return_value="/repo/golden-image.manifest.json"), \
             patch("feclora.deployment.client_runtime.restore_disk") as restore:
            result = execute_client_image_job(
                make_job("restore"), tls, self.approval,
                server_identity="URI:feclora-server", repository="/repo",
                trusted_server_public_key=None,
            )
        self.assertTrue(result[0])
        self.assertIsNone(restore.call_args.kwargs["minisign_public_key"])
        self.assertFalse(restore.call_args.kwargs["require_signature"])

    def test_save_captures_signs_then_announces_transfer(self):
        tls = FakeTLS()
        approval = LocalTargetApproval(
            "/dev/vda", "Virtual disk 1",
            "READ /dev/vda",
        )
        with patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device), \
             patch("feclora.deployment.client_runtime.shutil.which", return_value="/usr/bin/tool"), \
             patch("feclora.deployment.client_runtime.capture_disk") as capture, \
             patch("feclora.deployment.client_runtime.send_image_set") as send:
            result = execute_client_image_job(
                make_job("save"), tls, approval,
                server_identity="URI:feclora-server", repository="/repo",
                trusted_server_public_key="/trusted/server.pub",
                local_minisign_secret_key="/keys/client.key",
                local_minisign_public_key="/keys/client.pub",
                age_recipients_file="/keys/recipients.txt",
                encrypt_image=True, sign_image=True,
                transfer_progress_callback=lambda current, total: None,
            )
        self.assertTrue(result[0])
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["minisign_secret_key"], "/keys/client.key")
        self.assertEqual(capture.call_args.kwargs["age_recipients_file"], "/keys/recipients.txt")
        send.assert_called_once()
        self.assertIn(b"transfer_ready", bytes(tls.outgoing))

    def test_save_defaults_to_unencrypted_unsigned_even_when_keys_are_configured(self):
        tls = FakeTLS()
        approval = LocalTargetApproval(
            "/dev/vda", "Virtual disk 1",
            "READ /dev/vda",
        )
        with patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device), \
             patch("feclora.deployment.client_runtime.capture_disk") as capture, \
             patch("feclora.deployment.client_runtime.send_image_set") as send:
            result = execute_client_image_job(
                make_job("save"), tls, approval,
                server_identity="URI:feclora-server", repository="/repo",
                trusted_server_public_key="/trusted/server.pub",
                local_minisign_secret_key="/keys/client.key",
                local_minisign_public_key="/keys/client.pub",
                age_recipients_file="/keys/recipients.txt",
            )
        self.assertTrue(result[0])
        self.assertIsNone(capture.call_args.kwargs["minisign_secret_key"])
        self.assertIsNone(capture.call_args.kwargs["age_recipients_file"])
        self.assertIsNone(send.call_args.kwargs["trusted_public_key"])

    def test_remote_luks2_container_partition_restore_uses_verified_partition_engine(self):
        tls = FakeTLS(control_frame({
            "type": "transfer_offer", "job_id": JOB_ID, "image_id": "golden-image",
        }))
        with (
            patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device),
            patch("feclora.deployment.client_runtime.receive_image_set", return_value="/repo/golden-image.manifest.json"),
            patch("feclora.deployment.client_runtime.restore_partition") as restore_partition,
            patch("feclora.deployment.client_runtime.restore_disk") as restore_disk,
        ):
            result = execute_client_image_job(
                make_job("restore", "partition"), tls, self.approval,
                server_identity="URI:feclora-server", repository="/repo",
                trusted_server_public_key="/trusted/server.pub",
                age_identity_file="/keys/client.age",
            )
        self.assertTrue(result[0])
        restore_partition.assert_called_once()
        self.assertEqual(restore_partition.call_args.args[2], "/dev/vda")
        self.assertEqual(restore_partition.call_args.kwargs["confirmation"], "ERASE /dev/vda")
        self.assertEqual(restore_partition.call_args.kwargs["age_identity_file"], "/keys/client.age")
        restore_disk.assert_not_called()

    def test_clone_uses_existing_mutual_tls_socket_and_local_target_approval(self):
        job = DeploymentJob.from_dict({
            "schema_version": 1, "job_id": JOB_ID, "operation": "clone",
            "image_id": None, "source_device": "/dev/sda", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        })
        with patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device), \
             patch("feclora.deployment.client_runtime.receive_remote_disk",
                   return_value=SimpleNamespace(byte_count=4096, readback_sha256="a" * 64)) as receive:
            result = execute_client_image_job(
                job, FakeTLS(), self.approval,
                server_identity="URI:feclora-server",
                                repository="/repo",
                trusted_server_public_key="/trusted/server.pub",
            )
        self.assertTrue(result[0])
        self.assertIn("4096 bytes", result[1])
        receive.assert_called_once()
        self.assertEqual(receive.call_args.args[0].__class__, FakeTLS)
        self.assertEqual(receive.call_args.kwargs["local_identity"], "URI:feclora-client")
        self.assertEqual(receive.call_args.kwargs["expected_peer_identity"], "URI:feclora-server")
        self.assertEqual(receive.call_args.kwargs["target_path"], "/dev/vda")
        self.assertEqual(
            receive.call_args.kwargs["confirmation"],
            "ERASE /dev/vda",
        )

    def test_restore_rejects_wrong_local_confirmation_before_network_read(self):
        tls = FakeTLS()
        wrong = LocalTargetApproval(
            "/dev/vda", "Virtual disk 1",
            "ERASE /dev/vdb",
        )
        with patch("feclora.deployment.client_runtime.os.lstat", return_value=self.block_device):
            with self.assertRaisesRegex(ClientImageRuntimeError, "confirmation required"):
                execute_client_image_job(
                    make_job("restore"), tls, wrong,
                    server_identity="URI:feclora-server", repository="/repo",
                    trusted_server_public_key="/trusted/server.pub",
                )
        self.assertEqual(bytes(tls.outgoing), b"")


if __name__ == "__main__":
    unittest.main()
