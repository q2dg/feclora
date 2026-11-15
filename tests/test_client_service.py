import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from feclora.deployment.client_service import (
    ClientDeploymentService, ClientJobServiceError, mark_client_job_interrupted,
)


JOB_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
DEVICE = "/dev/sda"
SERVER_IDENTITY = "URI:feclora-server"


class ClientDeploymentServiceTests(unittest.TestCase):
    def _job(self, transport="unicast", target_bindings=None):
        from feclora.deployment.job import DeploymentJob
        payload = {
            "schema_version": 1, "job_id": JOB_ID, "operation": "restore",
            "image_id": "golden-image", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"] if transport == "unicast" else ["52:54:00:12:34:56", "52:54:00:12:34:57"],
            "network_interface": "enp1s0", "transport": transport,
            "multicast_group": "239.10.10.10" if transport == "multicast" else None,
            "multicast_port": 9000 if transport == "multicast" else None,
            "staging_required_bytes": 1024 if transport == "multicast" else None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        if target_bindings:
            payload["target_bindings"] = target_bindings
        return DeploymentJob.from_dict(payload)

    def test_find_device_resolves_only_unique_healthy_linear_or_thin_lv(self):
        inventory = {
            "devices": [{"type": "lvm", "path": "/dev/dm-2", "major_minor": "253:2", "size_bytes": 8 * 1024**3}],
            "volume_topology": {"status": "available", "volume_groups": [{
                "name": "vg0", "status": "healthy", "logical_volumes": [{
                    "name": "data", "path": "/dev/vg0/data", "major_minor": "253:2",
                    "segment_type": "linear", "size_bytes": 8 * 1024**3,
                    "health": None, "snapshot": False, "hidden": False,
                }],
            }]},
        }
        with mock.patch("feclora.deployment.client_service.collect_inventory", return_value=inventory):
            selected = ClientDeploymentService._find_device("/dev/vg0/data", "logical_volume")
        self.assertEqual(selected["path"], "/dev/vg0/data")
        self.assertEqual(selected["major_minor"], "253:2")
        self.assertEqual(selected["type"], "lvm")

    def test_find_device_rejects_unsupported_lv_layout(self):
        inventory = {
            "devices": [{"type": "lvm", "path": "/dev/dm-2", "major_minor": "253:2"}],
            "volume_topology": {"status": "available", "volume_groups": [{
                "name": "vg0", "status": "healthy", "logical_volumes": [{
                    "name": "data", "path": "/dev/vg0/data", "major_minor": "253:2",
                    "segment_type": "raid1", "health": None, "snapshot": False, "hidden": False,
                }],
            }]},
        }
        with mock.patch("feclora.deployment.client_service.collect_inventory", return_value=inventory):
            with self.assertRaisesRegex(ClientJobServiceError, "not uniquely present"):
                ClientDeploymentService._find_device("/dev/vg0/data", "logical_volume")

    def test_client_service_runs_only_after_server_start_and_persists_terminal_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / (JOB_ID + ".request.json")
            request.write_text(json.dumps({
                "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                "device_path": DEVICE,
                "confirmation": f"ERASE {DEVICE}",
                "compression": "gzip", "network_interface": "enp1s0", "source_address": "192.0.2.20", "igmp_confirmed": False, "image_encrypt": False, "image_sign": False,
            }), encoding="utf-8")
            request.chmod(0o600)
            service = ClientDeploymentService(JOB_ID)
            service.request_path = request
            service.status_path = root / (JOB_ID + ".status.json")
            service.lock_path = root / (JOB_ID + ".lock")
            config = SimpleNamespace(
                host="192.0.2.10", port=9443, local_identity="URI:client",
                server_identity=SERVER_IDENTITY, mac_address="52:54:00:12:34:56",
                ca_file="/ca.crt",
                age_identity_file=None, age_recipients_file=None, repository="/var/lib/feclora/images",
            )
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_stat = os.stat

            join_options = {}
            def fake_join(host, port, context, **kwargs):
                join_options.update(kwargs)
                job = self._job(target_bindings={
                    "52:54:00:12:34:56": {"wwn": "wwn-test-1", "serial": "SN-1"},
                })
                approval = kwargs["prepare_local_target"](job)
                success, detail = kwargs["execute_job"](job, object(), approval)
                return job, success, detail

            with mock.patch.object(service, "_acquire_lock"), \
                 mock.patch("feclora.deployment.service.recover_stale_runtime_artifacts"), \
                 mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service._write_private_json",
                            side_effect=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8")), \
                 mock.patch("feclora.deployment.client_service._read_private_json", return_value={
                     "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                     "device_path": DEVICE,
                     "confirmation": f"ERASE {DEVICE}",
                     "compression": "gzip", "network_interface": "enp1s0", "source_address": "192.0.2.20", "igmp_confirmed": False, "image_encrypt": False, "image_sign": False,
                 }), \
                 mock.patch("feclora.deployment.client_service.load_client_runtime_config", return_value=config), \
                 mock.patch("feclora.deployment.client_service.create_tls_context", return_value=object()), \
                 mock.patch.object(ClientDeploymentService, "_find_device", return_value={
                     "model": "Test disk", "size_bytes": 1024,
                    "serial": "SN-1", "wwn": "wwn-test-1",
                 }), \
                 mock.patch("feclora.deployment.client_service.check_capture_source_safe"), \
                 mock.patch("feclora.network.interface_discovery.discover_interface_addresses", return_value=[SimpleNamespace(address="192.0.2.20")]), \
                 mock.patch("feclora.deployment.client_service.os.stat",
                            side_effect=lambda path, *args, **kwargs: block_info if os.fspath(path) == DEVICE else real_stat(path, *args, **kwargs)), \
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
            self.assertEqual(join_options["source_address"], "192.0.2.20")
            self.assertEqual(join_options["network_interface"], "enp1s0")

    def test_multicast_job_preflights_selected_interface_and_uses_receiver_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / (JOB_ID + ".request.json")
            request.write_text(json.dumps({
                "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                "device_path": DEVICE,
                "confirmation": f"ERASE {DEVICE}",
                "compression": "gzip", "network_interface": "enp1s0", "igmp_confirmed": True,
            }), encoding="utf-8")
            request.chmod(0o600)
            service = ClientDeploymentService(JOB_ID)
            service.request_path = request
            service.status_path = root / (JOB_ID + ".status.json")
            service.lock_path = root / (JOB_ID + ".lock")
            config = SimpleNamespace(
                host="192.0.2.10", port=9443, local_identity="URI:client",
                server_identity=SERVER_IDENTITY, mac_address="52:54:00:12:34:56",
                ca_file="/ca.crt",
                age_identity_file="/age.identity", age_recipients_file="/age-recipients.txt",
                repository="/var/lib/feclora/images",
            )
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_stat = os.stat

            def fake_join(host, port, context, **kwargs):
                job = self._job("multicast")
                approval = kwargs["prepare_local_target"](job)
                success, detail = kwargs["execute_job"](job, object(), approval)
                return job, success, detail

            preflight = SimpleNamespace(warnings=("Verify IGMP snooping and querier.",))
            with mock.patch.object(service, "_acquire_lock"), \
                 mock.patch("feclora.deployment.service.recover_stale_runtime_artifacts"), \
                 mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service._write_private_json",
                            side_effect=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8")), \
                 mock.patch("feclora.deployment.client_service._read_private_json", return_value={
                     "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                     "device_path": DEVICE,
                     "confirmation": f"ERASE {DEVICE}",
                     "compression": "gzip", "network_interface": "enp1s0",
                     "igmp_confirmed": True,
                 }), \
                 mock.patch("feclora.deployment.client_service.load_client_runtime_config", return_value=config), \
                 mock.patch("feclora.deployment.client_service.create_tls_context", return_value=object()), \
                 mock.patch.object(ClientDeploymentService, "_find_device", return_value={"model": "Test disk"}), \
                 mock.patch("feclora.deployment.client_service.check_capture_source_safe"), \
                 mock.patch("feclora.deployment.client_service.os.stat",
                            side_effect=lambda path, *args, **kwargs: block_info if os.fspath(path) == DEVICE else real_stat(path, *args, **kwargs)), \
                 mock.patch("feclora.deployment.client_service.inspect_multicast_interface", return_value=preflight) as inspect, \
                 mock.patch("feclora.deployment.client_service.shutil.disk_usage", return_value=SimpleNamespace(free=1024 * 1024 * 1024)), \
                 mock.patch("feclora.deployment.client_service.join_deployment", side_effect=fake_join), \
                 mock.patch("feclora.deployment.client_service.execute_multicast_restore",
                            return_value=(True, "multicast image restored")) as execute:
                service.run()

            status = json.loads(service.status_path.read_text(encoding="utf-8"))
            inspect.assert_called_once_with("enp1s0", "239.10.10.10", role="receiver")
            execute.assert_called_once()
            self.assertEqual(execute.call_args.kwargs["network_interface"], "enp1s0")
            self.assertEqual(status["network_interface"], "enp1s0")
            self.assertEqual(status["multicast_warnings"], list(preflight.warnings))
            self.assertEqual(status["phase"], "completed")

    def test_multicast_insufficient_staging_capacity_fails_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / (JOB_ID + ".request.json")
            request.write_text(json.dumps({
                "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                "device_path": DEVICE,
                "confirmation": f"ERASE {DEVICE}",
                "compression": "gzip", "network_interface": "enp1s0", "igmp_confirmed": True,
            }), encoding="utf-8")
            request.chmod(0o600)
            service = ClientDeploymentService(JOB_ID)
            service.request_path = request
            service.status_path = root / (JOB_ID + ".status.json")
            service.lock_path = root / (JOB_ID + ".lock")
            config = SimpleNamespace(
                host="192.0.2.10", port=9443, local_identity="URI:client",
                server_identity=SERVER_IDENTITY, mac_address="52:54:00:12:34:56",
                ca_file="/ca.crt", trusted_server_public_key="/server.pub",
                age_identity_file="/age.identity", age_recipients_file="/age-recipients.txt",
                repository="/var/lib/feclora/images",
            )
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_lstat = os.lstat

            def fake_join(host, port, context, **kwargs):
                job = self._job("multicast")
                approval = kwargs["prepare_local_target"](job)
                success, detail = kwargs["execute_job"](job, object(), approval)
                return job, success, detail

            preflight = SimpleNamespace(warnings=("Verify IGMP snooping and querier.",))
            with mock.patch.object(service, "_acquire_lock"), \
                 mock.patch("feclora.deployment.service.recover_stale_runtime_artifacts"), \
                 mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service._write_private_json",
                            side_effect=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8")), \
                 mock.patch("feclora.deployment.client_service._read_private_json", return_value={
                     "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                     "device_path": DEVICE,
                     "confirmation": f"ERASE {DEVICE}",
                     "compression": "gzip", "network_interface": "enp1s0",
                     "igmp_confirmed": True,
                 }), \
                 mock.patch("feclora.deployment.client_service.load_client_runtime_config", return_value=config), \
                 mock.patch("feclora.deployment.client_service.create_tls_context", return_value=object()), \
                 mock.patch.object(ClientDeploymentService, "_find_device", return_value={"model": "Test disk"}), \
                 mock.patch("feclora.deployment.client_service.check_capture_source_safe"), \
                 mock.patch("feclora.deployment.client_service.os.lstat",
                            side_effect=lambda path: block_info if os.fspath(path) == DEVICE else real_lstat(path)), \
                 mock.patch("feclora.deployment.client_service.inspect_multicast_interface", return_value=preflight) as inspect, \
                 mock.patch("feclora.deployment.client_service.shutil.disk_usage", return_value=SimpleNamespace(free=1)), \
                 mock.patch("feclora.deployment.client_service.join_deployment", side_effect=fake_join), \
                 mock.patch("feclora.deployment.client_service.execute_multicast_restore",
                            return_value=(True, "multicast image restored")) as execute:
                service.run()

            status = json.loads(service.status_path.read_text(encoding="utf-8"))
            inspect.assert_called_once_with("enp1s0", "239.10.10.10", role="receiver")
            execute.assert_not_called()
            self.assertEqual(status["phase"], "failed")
            self.assertIn("insufficient Client staging capacity before READY", status["detail"])
            self.assertNotEqual(status["phase"], "ready")

    def test_unattended_shared_answer_request_resolves_bound_disk_and_uses_handoff_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / (JOB_ID + ".request.json")
            request_path.write_text("{}", encoding="utf-8")
            request_path.chmod(0o600)
            service = ClientDeploymentService(JOB_ID)
            service.request_path = request_path
            service.status_path = root / (JOB_ID + ".status.json")
            service.lock_path = root / (JOB_ID + ".lock")
            request = {
                "schema_version": 1, "job_id": JOB_ID, "host": "192.0.2.10",
                "port": 9555, "device_path": None, "confirmation": None,
                "compression": "none", "network_interface": None,
                "igmp_confirmed": False, "image_encrypt": False,
                "image_sign": False, "unattended": True,
            }
            config = SimpleNamespace(
                host="192.0.2.10", port=9443,
                server_identity=SERVER_IDENTITY, mac_address="52:54:00:12:34:56",
                ca_file="/ca.crt",
                age_identity_file=None, age_recipients_file=None,
                repository="/var/lib/feclora/images",
            )
            selected = {
                "type": "disk", "path": DEVICE, "wwn": "wwn-01",
                "serial": "serial-01", "model": "Test disk", "size_bytes": 1024,
            }
            job = self._job(target_bindings={
                "52:54:00:12:34:56": {"wwn": "wwn-01", "serial": "serial-01"},
            })
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_stat = os.stat

            def fake_execute_client_image_job(*args, **kwargs):
                self.assertTrue(callable(kwargs["pre_write_callback"]))
                kwargs["pre_write_callback"]()
                return True, "restore completed"

            def fake_join(host, port, context, **kwargs):
                approval = kwargs["prepare_local_target"](job)
                self.assertEqual(approval.device_path, DEVICE)
                self.assertEqual(approval.confirmation, f"ERASE {DEVICE}")
                success, detail = kwargs["execute_job"](job, object(), approval)
                return job, success, detail

            with mock.patch.object(service, "_acquire_lock"), \
                 mock.patch("feclora.deployment.service.recover_stale_runtime_artifacts"), \
                 mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service._read_private_json", return_value=request), \
                 mock.patch("feclora.deployment.client_service._write_private_json", side_effect=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8")), \
                 mock.patch("feclora.deployment.client_service.load_client_runtime_config", return_value=config), \
                 mock.patch("feclora.deployment.client_service.create_tls_context", return_value=object()), \
                 mock.patch.object(ClientDeploymentService, "_find_device", return_value=selected), \
                 mock.patch("feclora.deployment.client_service.check_capture_source_safe"), \
                 mock.patch("feclora.deployment.client_service.os.stat", side_effect=lambda path, *args, **kwargs: block_info if os.fspath(path) == DEVICE else real_stat(path, *args, **kwargs)), \
                 mock.patch("feclora.deployment.client_service.execute_client_image_job", side_effect=fake_execute_client_image_job), \
                 mock.patch("feclora.deployment.client_service.join_deployment", side_effect=fake_join) as join, \
                 mock.patch.object(ClientDeploymentService, "_find_unattended_disk", return_value=selected) as resolve_target:
                service.run()

            join.assert_called_once()
            self.assertEqual(resolve_target.call_count, 2)
            self.assertEqual(join.call_args.args[0], "192.0.2.10")
            self.assertEqual(join.call_args.args[1], 9555)
            status = json.loads(service.status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["phase"], "completed")
            self.assertTrue(status["success"])


    def test_unattended_pxe_multicast_resolves_shared_mac_target_binding(self):
        from feclora.deployment.job import DeploymentJob
        from feclora.deployment.client_service import _select_unattended_multicast_interface
        payload = {
            "schema_version": 1, "job_id": JOB_ID, "operation": "restore",
            "image_id": "golden", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
            "network_interface": "auto", "transport": "multicast",
            "multicast_group": "239.10.10.10", "multicast_port": 5000,
            "start_policy": "automatic", "expected_clients": None, "start_deadline": None,
            "repository_id": "nas-images", "boot_method": "pxe",
            "confirm_destructive": True,
            "target_bindings": {
                "52:54:00:12:34:56": {"wwn": "wwn-client-1", "serial": None},
                "52:54:00:12:34:57": {"wwn": "wwn-client-2", "serial": None},
            },
        }
        job = DeploymentJob.from_dict(payload)
        selected = {
            "type": "disk", "path": DEVICE, "wwn": "wwn-client-2",
            "serial": None, "model": "Client disk",
        }
        with mock.patch("feclora.deployment.client_service.collect_inventory", return_value={
            "devices": [selected],
        }):
            resolved = ClientDeploymentService._find_unattended_disk(
                job, "52:54:00:12:34:57",
            )
        self.assertEqual(resolved["path"], DEVICE)
        with mock.patch("feclora.deployment.client_service.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout="239.10.10.10 dev enp2s0 src 192.0.2.22\\n",
        )) as route:
            self.assertEqual(_select_unattended_multicast_interface("239.10.10.10"), "enp2s0")
        route.assert_called_once()

    def test_orderly_signal_does_not_interrupt_active_block_device_io(self):
        service = ClientDeploymentService(JOB_ID)
        service._phase = "running"
        service._handle_signal(15, None)
        service._phase = "ready"
        with self.assertRaises(SystemExit):
            service._handle_signal(15, None)

    def test_client_services_share_one_host_wide_execution_lock(self):
        from feclora.deployment.client_service import _job_paths
        other = "d47ac10b-58cc-4372-a567-0e02b2c3d480"
        self.assertEqual(_job_paths(JOB_ID)[2], _job_paths(other)[2])

    def test_job_paths_reject_noncanonical_uuid(self):
        from feclora.deployment.client_service import ClientJobServiceError, _job_paths
        with self.assertRaisesRegex(ClientJobServiceError, "canonical UUID"):
            _job_paths("../unsafe")

    def test_process_exit_marks_nonterminal_client_job_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_path = root / f"{JOB_ID}.status.json"
            status_path.write_text(json.dumps({
                "schema_version": 1, "job_id": JOB_ID,
                "phase": "running", "success": None,
                "detail": "restoring", "progress": {"completed_bytes": 4096},
            }), encoding="utf-8")
            status_path.chmod(0o600)
            info = os.stat(status_path, follow_symlinks=False)
            root_owned_info = SimpleNamespace(
                st_mode=info.st_mode, st_uid=0, st_size=info.st_size,
                st_dev=info.st_dev, st_ino=info.st_ino,
            )
            with mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service.os.lstat", return_value=root_owned_info), \
                 mock.patch("feclora.deployment.client_service.os.fstat", return_value=root_owned_info):
                mark_client_job_interrupted(JOB_ID)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["phase"], "interrupted")
            self.assertFalse(status["success"])
            self.assertIn("No automatic reconnect or storage resume", status["detail"])
            self.assertEqual(status["progress"], {"completed_bytes": 4096})

    def test_process_exit_preserves_terminal_client_job_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_path = root / f"{JOB_ID}.status.json"
            original = {
                "schema_version": 1, "job_id": JOB_ID,
                "phase": "completed", "success": True,
                "detail": "verified", "progress": {"completed_bytes": 8192},
            }
            status_path.write_text(json.dumps(original), encoding="utf-8")
            status_path.chmod(0o600)
            info = os.stat(status_path, follow_symlinks=False)
            root_owned_info = SimpleNamespace(
                st_mode=info.st_mode, st_uid=0, st_size=info.st_size,
                st_dev=info.st_dev, st_ino=info.st_ino,
            )
            with mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"), \
                 mock.patch("feclora.deployment.client_service.os.lstat", return_value=root_owned_info), \
                 mock.patch("feclora.deployment.client_service.os.fstat", return_value=root_owned_info):
                mark_client_job_interrupted(JOB_ID)
            self.assertEqual(json.loads(status_path.read_text(encoding="utf-8")), original)

    def test_process_exit_without_client_status_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch("feclora.deployment.client_service.CLIENT_JOB_DIRECTORY", root), \
                 mock.patch("feclora.deployment.client_service._ensure_directory"):
                mark_client_job_interrupted(JOB_ID)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
