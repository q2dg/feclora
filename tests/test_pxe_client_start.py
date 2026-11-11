import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.pxe_client_start import start_unattended_pxe_client
from feclora.deployment.client_service import ClientDeploymentService, ClientJobServiceError


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"


class PXEClientStartTests(unittest.TestCase):
    def test_interactive_boot_does_not_load_identity_or_start_client(self):
        with tempfile.TemporaryDirectory() as directory:
            cmdline = Path(directory) / "cmdline"
            cmdline.write_text("quiet feclora.pxe_mode=interactive", encoding="utf-8")
            with patch("feclora.deployment.pxe_client_start.load_client_runtime_config") as load, patch(
                "feclora.deployment.pxe_client_start.subprocess.run"
            ) as run:
                self.assertIsNone(start_unattended_pxe_client(command_line_path=str(cmdline)))
            load.assert_not_called()
            run.assert_not_called()

    def test_unattended_handoff_creates_private_job_request_and_starts_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cmdline = root / "cmdline"
            cmdline.write_text(
                f"quiet feclora.pxe_mode=unattended feclora.pxe_job_id={JOB_ID} "
                "feclora.pxe_server=192.0.2.10 feclora.pxe_control_port=9555",
                encoding="utf-8",
            )
            request = root / f"{JOB_ID}.request.json"
            status = root / f"{JOB_ID}.status.json"
            config = SimpleNamespace(local_identity="URI:feclora-client-lab")
            with patch("feclora.deployment.pxe_client_start.load_client_runtime_config", return_value=config), patch(
                "feclora.deployment.pxe_client_start._ensure_directory"
            ), patch("feclora.deployment.pxe_client_start._job_paths", return_value=(request, status, root / "lock")), patch(
                "feclora.deployment.pxe_client_start.CLIENT_CONFIG", str(root / "identity.json")
            ), patch("feclora.deployment.pxe_client_start._write_private_json", side_effect=lambda path, value: (Path(path).write_text(json.dumps(value), encoding="utf-8"), Path(path).chmod(0o600))), patch("feclora.deployment.pxe_client_start.subprocess.run") as run:
                result = start_unattended_pxe_client(command_line_path=str(cmdline))
            self.assertEqual(result, JOB_ID)
            payload = json.loads(request.read_text(encoding="utf-8"))
            self.assertTrue(payload["unattended"])
            self.assertEqual(payload["host"], "192.0.2.10")
            self.assertEqual(payload["port"], 9555)
            self.assertIsNone(payload["device_path"])
            self.assertIsNone(payload["confirmation"])
            self.assertEqual(request.stat().st_mode & 0o777, 0o600)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-1], f"feclora-pxe-client@{JOB_ID}.service")
            self.assertEqual(run.call_args_list[0].args[0][-1], "mnt-feclora\\x2dpxe\\x2didentity.mount")

    def test_unattended_start_refuses_existing_job_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cmdline = root / "cmdline"
            cmdline.write_text(
                f"feclora.pxe_mode=unattended feclora.pxe_job_id={JOB_ID} "
                "feclora.pxe_server=192.0.2.10 feclora.pxe_control_port=9443",
                encoding="utf-8",
            )
            request = root / f"{JOB_ID}.request.json"
            request.write_text("existing", encoding="utf-8")
            with patch("feclora.deployment.pxe_client_start.load_client_runtime_config", return_value=object()), patch(
                "feclora.deployment.pxe_client_start._ensure_directory"
            ), patch("feclora.deployment.pxe_client_start._job_paths", return_value=(request, root / "status", root / "lock")), patch(
                "feclora.deployment.pxe_client_start.subprocess.run"
            ):
                with self.assertRaisesRegex(ClientJobServiceError, "already has a local request"):
                    start_unattended_pxe_client(command_line_path=str(cmdline))

    def test_unattended_disk_resolution_requires_unique_bound_hardware_identity(self):
        job = SimpleNamespace(
            operation="restore", transport="unicast", target_type="disk",
            target_bindings=(("52:54:00:12:34:56", "wwn-01", "serial-01"),),
        )
        inventory = {"devices": [
            {"type": "disk", "path": "/dev/sda", "wwn": "wwn-01", "serial": "serial-01"},
            {"type": "disk", "path": "/dev/sdb", "wwn": "wwn-02", "serial": "serial-02"},
        ]}
        with patch("feclora.deployment.client_service.collect_inventory", return_value=inventory):
            result = ClientDeploymentService._find_unattended_disk(job, "52:54:00:12:34:56")
        self.assertEqual(result["path"], "/dev/sda")
        duplicate = {"devices": inventory["devices"] + [dict(inventory["devices"][0], path="/dev/sdc")]}
        with patch("feclora.deployment.client_service.collect_inventory", return_value=duplicate):
            with self.assertRaisesRegex(ClientJobServiceError, "exactly one"):
                ClientDeploymentService._find_unattended_disk(job, "52:54:00:12:34:56")

    def test_unattended_disk_resolution_rejects_unbound_job(self):
        job = SimpleNamespace(
            operation="restore", transport="unicast", target_type="disk",
            target_bindings=(),
        )
        with self.assertRaisesRegex(ClientJobServiceError, "must bind"):
            ClientDeploymentService._find_unattended_disk(job, "52:54:00:12:34:56")


if __name__ == "__main__":
    unittest.main()
