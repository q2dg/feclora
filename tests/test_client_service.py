import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from feclora.deployment.client_service import ClientDeploymentService


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
DEVICE = "/dev/sda"
SERVER_IDENTITY = "URI:feclora-server"


class ClientDeploymentServiceTests(unittest.TestCase):
    def _job(self):
        from feclora.deployment.job import DeploymentJob
        return DeploymentJob.from_dict({
            "schema_version": 1, "job_id": JOB_ID, "operation": "restore",
            "image_id": "golden-image", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        })

    def test_client_service_runs_only_after_server_start_and_persists_terminal_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / (JOB_ID + ".request.json")
            request.write_text(json.dumps({
                "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                "device_path": DEVICE,
                "confirmation": f"ERASE {DEVICE} FROM {SERVER_IDENTITY}",
                "compression": "gzip",
            }), encoding="utf-8")
            request.chmod(0o600)
            service = ClientDeploymentService(JOB_ID)
            service.request_path = request
            service.status_path = root / (JOB_ID + ".status.json")
            service.lock_path = root / (JOB_ID + ".lock")
            config = SimpleNamespace(
                host="192.0.2.10", port=9443, local_identity="URI:client",
                server_identity=SERVER_IDENTITY, mac_address="52:54:00:12:34:56",
                ca_file="/ca.crt", certificate_file="/client.crt",
                private_key_file="/client.key", trusted_server_public_key="/server.pub",
                local_minisign_secret_key=None, local_minisign_public_key=None,
                age_identity_file=None, age_recipients_file=None, repository="/var/lib/feclora/images",
            )
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_lstat = os.lstat

            def fake_join(host, port, context, **kwargs):
                job = self._job()
                approval = kwargs["prepare_local_target"](job)
                success, detail = kwargs["execute_job"](job, object(), approval)
                return job, success, detail

            with mock.patch.object(service, "_acquire_lock"), \
                 mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service._read_private_json", return_value={
                     "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                     "device_path": DEVICE,
                     "confirmation": f"ERASE {DEVICE} FROM {SERVER_IDENTITY}",
                     "compression": "gzip",
                 }), \
                 mock.patch("feclora.deployment.client_service.load_client_runtime_config", return_value=config), \
                 mock.patch("feclora.deployment.client_service.create_mutual_tls_context", return_value=object()), \
                 mock.patch.object(ClientDeploymentService, "_find_device", return_value={
                     "model": "Test disk", "size_bytes": 1024, "serial": "SN-1",
                 }), \
                 mock.patch("feclora.deployment.client_service.check_capture_source_safe"), \
                 mock.patch("feclora.deployment.client_service.os.lstat",
                            side_effect=lambda path: block_info if os.fspath(path) == DEVICE else real_lstat(path)), \
                 mock.patch("feclora.deployment.client_service.join_deployment", side_effect=fake_join), \
                 mock.patch("feclora.deployment.client_service.execute_client_image_job",
                            return_value=(True, "image restored and verified")) as execute:
                service.run()

            status = json.loads(service.status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["phase"], "completed")
            self.assertTrue(status["success"])
            self.assertEqual(status["target_description"], "Test disk 1024 SN-1")
            self.assertFalse(request.exists())
            execute.assert_called_once()

    def test_job_paths_reject_noncanonical_uuid(self):
        from feclora.deployment.client_service import ClientJobServiceError, _job_paths
        with self.assertRaisesRegex(ClientJobServiceError, "canonical UUID"):
            _job_paths("../unsafe")


if __name__ == "__main__":
    unittest.main()
