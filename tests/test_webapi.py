import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.webapi import WebAPIError, dispatch, _device
from feclora.deployment.job import DeploymentJob


class WebAPITests(unittest.TestCase):
    def test_rejects_unknown_or_extra_request_fields(self):
        with self.assertRaisesRegex(WebAPIError, "action and optional params"):
            dispatch({"action": "status", "command": "id"})
        with self.assertRaisesRegex(WebAPIError, "unsupported"):
            dispatch({"action": "shell"})

    def test_rejects_parameters_for_read_only_actions(self):
        with self.assertRaisesRegex(WebAPIError, "does not accept parameters"):
            dispatch({"action": "status", "params": {"command": "id"}})

    def test_inventory_action_returns_only_inventory(self):
        with patch("feclora.webapi.collect_inventory", return_value={"devices": []}) as inventory:
            self.assertEqual(dispatch({"action": "inventory"}), {"devices": []})
        inventory.assert_called_once_with()

    def test_images_action_uses_manifest_inventory(self):
        with patch("feclora.webapi._images", return_value=[{"image_id": "base"}]):
            self.assertEqual(dispatch({"action": "images"}), {"images": [{"image_id": "base"}]})

    def test_operations_action_returns_durable_local_history(self):
        expected = [{"operation": "capture_disk", "status": "completed"}]
        with patch("feclora.webapi._operations", return_value=expected):
            self.assertEqual(dispatch({"action": "operations"}), {"operations": expected})

    def test_network_interfaces_action_returns_discovered_bindings(self):
        expected = [{"interface": "enp1s0", "address": "192.0.2.10", "prefix_length": 24,
                     "dhcp_server": None, "binding": "enp1s0|192.0.2.10|24"}]
        with patch("feclora.webapi._network_interfaces", return_value=expected):
            self.assertEqual(dispatch({"action": "network_interfaces"}), {"interfaces": expected})

    def test_prepare_client_request_is_exposed_through_allowlisted_api(self):
        with patch("feclora.webapi._prepare_client_request", return_value={"identity": "URI:feclora-client-lab"}) as prepare:
            result = dispatch({"action": "prepare_client_request", "params": {"client_id": "lab"}})
        prepare.assert_called_once_with({"client_id": "lab"})
        self.assertEqual(result["identity"], "URI:feclora-client-lab")

    def test_complete_client_enrollment_is_exposed_through_allowlisted_api(self):
        with patch("feclora.webapi._complete_client_enrollment", return_value={"identity": "URI:feclora-client-lab"}) as complete:
            result = dispatch({"action": "complete_client_enrollment", "params": {"client_id": "lab"}})
        complete.assert_called_once_with({"client_id": "lab"})
        self.assertEqual(result["identity"], "URI:feclora-client-lab")
    def test_inspect_client_csr_is_exposed_through_allowlisted_api(self):
        with patch("feclora.webapi._inspect_client_csr", return_value={"identity": "URI:feclora-client-lab"}) as inspect:
            result = dispatch({"action": "inspect_client_csr", "params": {"csr_path": "/run/media/usb/request.csr"}})
        inspect.assert_called_once_with({"csr_path": "/run/media/usb/request.csr"})
        self.assertEqual(result["identity"], "URI:feclora-client-lab")

    def test_approve_client_csr_is_exposed_through_allowlisted_api(self):
        with patch("feclora.webapi._approve_client_csr", return_value={"identity": "URI:feclora-client-lab"}) as approve:
            result = dispatch({"action": "approve_client_csr", "params": {"confirmation": "ENROLL"}})
        approve.assert_called_once_with({"confirmation": "ENROLL"})
        self.assertEqual(result["identity"], "URI:feclora-client-lab")
    def test_bootstrap_server_requires_exact_parameters(self):
        with self.assertRaisesRegex(WebAPIError, "requires interface"):
            dispatch({"action": "bootstrap_server", "params": {"address": "192.0.2.10"}})

    def test_bootstrap_server_initializes_only_an_assigned_address(self):
        config = SimpleNamespace(
            bind_address="192.0.2.10", port=9443, local_identity="URI:feclora-server",
            client_identity_to_mac={}
        )
        with patch("feclora.network.interface_discovery.discover_interface_addresses", return_value=["address"]) as discover, \
             patch("feclora.network.interface_discovery.validate_selected_address") as validate, \
             patch("feclora.deployment.bootstrap.ensure_server_deployment_config", return_value=True) as bootstrap, \
             patch("feclora.deployment.runtime_config.load_server_runtime_config", return_value=config):
            result = dispatch({"action": "bootstrap_server", "params": {
                "interface": "enp1s0", "address": "192.0.2.10", "prefix_length": 24
            }})
        discover.assert_called_once_with("enp1s0")
        validate.assert_called_once_with("enp1s0", "192.0.2.10", 24, ["address"])
        bootstrap.assert_called_once_with("192.0.2.10")
        self.assertTrue(result["created"])
        self.assertEqual(result["bind_address"], "192.0.2.10")
        self.assertEqual(result["enrolled_clients"], 0)

    def test_bootstrap_server_validates_address_and_prefix_before_bootstrap(self):
        with self.assertRaisesRegex(WebAPIError, "prefix_length"):
            dispatch({"action": "bootstrap_server", "params": {
                "interface": "enp1s0", "address": "192.0.2.10", "prefix_length": True
            }})
        with self.assertRaisesRegex(WebAPIError, "IPv4"):
            dispatch({"action": "bootstrap_server", "params": {
                "interface": "enp1s0", "address": "2001:db8::1", "prefix_length": 24
            }})

    def test_validate_pxe_profile_runs_daemon_preflight_without_starting_services(self):
        with patch("feclora.network.pxe_preflight.validate_pxe_configuration") as preflight, \
             patch("feclora.network.interface_discovery.detect_existing_dhcp_server", return_value=None):
            result = dispatch({"action": "validate_pxe_profile", "params": {
                "interface": "enp1s0", "address": "192.0.2.1", "prefix_length": 24,
                "mode": "proxy", "pool_start": None, "pool_end": None,
                "lease_time": "1h", "gateway": None, "dns_server": None,
                "http_port": 8080, "authoritative_confirmed": False,
            }})
        preflight.assert_called_once()
        self.assertTrue(result["valid"])
        self.assertFalse(result["services_started"])
        self.assertEqual(result["subnet"], "192.0.2.0/24")

    def test_validate_pxe_profile_rejects_existing_dhcp_for_isolated_mode(self):
        with patch("feclora.network.pxe_preflight.validate_pxe_configuration"), \
             patch("feclora.network.interface_discovery.detect_existing_dhcp_server", return_value="192.0.2.254"):
            with self.assertRaisesRegex(WebAPIError, "existing DHCP server"):
                dispatch({"action": "validate_pxe_profile", "params": {
                    "interface": "enp1s0", "address": "192.0.2.1", "prefix_length": 24,
                    "mode": "isolated", "pool_start": "192.0.2.100", "pool_end": "192.0.2.180",
                    "lease_time": "1h", "gateway": None, "dns_server": None,
                    "http_port": 8080, "authoritative_confirmed": True,
                }})

    def test_start_pxe_services_requires_successful_preflight_and_uses_manager(self):
        class Manager:
            def __init__(self): self.started = []
            def start(self, config): self.started.append(config)
            def status(self): return {"active": True, "interface": "enp1s0", "services": {"dnsmasq": "active"}}
        manager = Manager()
        params = {
            "interface": "enp1s0", "address": "192.0.2.1", "prefix_length": 24,
            "mode": "proxy", "pool_start": None, "pool_end": None,
            "lease_time": "1h", "gateway": None, "dns_server": None,
            "http_port": 8080, "authoritative_confirmed": False,
        }
        with patch("feclora.network.pxe_preflight.validate_pxe_configuration"), patch("feclora.network.interface_discovery.detect_existing_dhcp_server", return_value=None), patch("feclora.network.pxe_service.PXEServiceManager", return_value=manager):
            result = dispatch({"action": "start_pxe_services", "params": params})
        self.assertTrue(result["active"])
        self.assertEqual(len(manager.started), 1)
        self.assertEqual(manager.started[0].interface, "enp1s0")

    def test_stop_pxe_services_restores_firewall_and_reports_inactive_state(self):
        class Manager:
            def __init__(self):
                self.stopped = False
            def stop(self):
                self.stopped = True
            def status(self):
                return {"active": False, "configured": False, "interface": None, "services": {}}

        manager = Manager()
        with patch("feclora.network.pxe_service.PXEServiceManager", return_value=manager):
            result = dispatch({"action": "stop_pxe_services"})
        self.assertTrue(manager.stopped)
        self.assertFalse(result["active"])
        self.assertIn("previous firewalld zone restored", result["message"])

    def test_stop_pxe_services_reports_incomplete_cleanup(self):
        class Manager:
            def stop(self):
                pass
            def status(self):
                return {"active": True, "configured": True, "interface": "enp1s0",
                        "services": {"dnsmasq": "active"}}

        with patch("feclora.network.pxe_service.PXEServiceManager", return_value=Manager()):
            result = dispatch({"action": "stop_pxe_services"})
        self.assertTrue(result["active"])
        self.assertIn("shutdown is incomplete", result["message"])

    def test_stop_pxe_services_rejects_parameters(self):
        with self.assertRaisesRegex(WebAPIError, "does not accept parameters"):
            dispatch({"action": "stop_pxe_services", "params": {"interface": "enp1s0"}})

    def test_validate_pxe_profile_rejects_unknown_fields(self):
        with self.assertRaisesRegex(WebAPIError, "complete PXE profile"):
            dispatch({"action": "validate_pxe_profile", "params": {"mode": "proxy"}})

    def test_deployment_jobs_returns_empty_before_first_job_exists(self):
        with patch("feclora.webapi.os.path.lexists", return_value=False):
            self.assertEqual(dispatch({"action": "deployment_jobs"}), {"jobs": []})

    def test_deployment_jobs_action_is_read_only(self):
        expected = [{"job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"}]
        with patch("feclora.webapi._deployment_jobs", return_value=expected):
            self.assertEqual(dispatch({"action": "deployment_jobs"}), {"jobs": expected})
        with self.assertRaisesRegex(WebAPIError, "does not accept parameters"):
            dispatch({"action": "deployment_jobs", "params": {"x": 1}})

    def test_create_deployment_job_requires_exact_job_envelope(self):
        with self.assertRaisesRegex(WebAPIError, "exactly one job object"):
            dispatch({"action": "create_deployment_job", "params": {"job": {}, "extra": True}})

    def test_create_deployment_job_validates_job_before_server_configuration(self):
        invalid_job = {
            "schema_version": 1, "job_id": "not-a-uuid",
            "operation": "save", "image_id": "lab-capture", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with self.assertRaisesRegex(WebAPIError, "job_id must be a UUID"):
            dispatch({"action": "create_deployment_job", "params": {"job": invalid_job}})

    def test_create_deployment_job_persists_valid_definition_without_starting_io(self):
        import tempfile
        from pathlib import Path
        server_config = SimpleNamespace(
            client_identity_to_mac={"URI:feclora-client-lab": "52:54:00:12:34:56"},
            client_minisign_public_keys={"52:54:00:12:34:56": "/etc/feclora/pki/client.pub"},
        )
        payload = {
            "schema_version": 1, "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
            "operation": "save", "image_id": "lab-capture", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"], "network_interface": "enp1s0",
            "transport": "unicast", "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch("feclora.deployment.runtime_config.load_server_runtime_config", return_value=server_config), patch(
                "feclora.webapi.socket.if_nameindex", return_value=[(2, "enp1s0")]
            ), patch("feclora.webapi._images", return_value=[]), patch(
                "feclora.webapi._deployment_journal_directory", return_value=Path(directory)
            ):
                result = dispatch({"action": "create_deployment_job", "params": {"job": payload}})
                from feclora.deployment.journal import DeploymentJournal
                report = DeploymentJournal.inspect(
                    Path(directory) / (payload["job_id"] + ".jsonl")
                ).recovery_report()
        self.assertFalse(result["started"])
        self.assertEqual(result["job_state"], "created")
        self.assertEqual(report["job"]["image_id"], "lab-capture")
        self.assertEqual(report["job_state"], "created")

    def test_reconcile_deployment_job_requires_exact_operator_confirmation(self):
        import tempfile
        from pathlib import Path
        from feclora.deployment.coordinator import DeploymentCoordinator
        from feclora.deployment.journal import DeploymentJournal

        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        job = {
            "schema_version": 1, "job_id": job_id, "operation": "save",
            "image_id": "lab-capture", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            journal = DeploymentJournal(Path(directory) / f"{job_id}.jsonl", job_id)
            DeploymentCoordinator(DeploymentJob.from_dict(job), event_sink=journal)
            journal({
                "timestamp": "2026-11-08T12:00:00+00:00", "job_id": job_id,
                "event": "service_started", "job_state": "created",
            })
            with patch("feclora.webapi._deployment_journal_directory", return_value=Path(directory)):
                with self.assertRaisesRegex(WebAPIError, "confirmation does not match"):
                    dispatch({"action": "reconcile_deployment_job", "params": {
                        "job_id": job_id, "confirmation": "RECONCILE wrong",
                    }})
                result = dispatch({"action": "reconcile_deployment_job", "params": {
                    "job_id": job_id, "confirmation": f"RECONCILE {job_id}",
                }})
                report = DeploymentJournal.inspect(Path(directory) / f"{job_id}.jsonl").recovery_report()
        self.assertEqual(result["job_state"], "failed")
        self.assertFalse(result["interrupted"])
        self.assertTrue(result["operator_reconciled"])
        self.assertEqual(report["last_event"], "operator_reconciled")
        self.assertFalse(report["automatic_resume"])

    def test_reconcile_deployment_job_rejects_extra_parameters(self):
        with self.assertRaisesRegex(WebAPIError, "exactly job_id and confirmation"):
            dispatch({"action": "reconcile_deployment_job", "params": {
                "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "confirmation": "RECONCILE f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "force": True,
            }})

    def test_device_paths_are_restricted_to_dev_nodes(self):
        self.assertEqual(_device("/dev/nvme0n1p2", "target"), "/dev/nvme0n1p2")
        for invalid in ("/etc/passwd", "/dev/../etc/shadow", "sda", "/dev/sda;id"):
            with self.subTest(invalid=invalid), self.assertRaises(WebAPIError):
                _device(invalid, "target")

    def test_destructive_action_requires_exact_parameter_set(self):
        with self.assertRaisesRegex(WebAPIError, "parameters do not match"):
            dispatch({"action": "clone_disk", "params": {"source": "/dev/sda", "target": "/dev/sdb"}})

    def test_start_deployment_service_uses_validated_systemd_instance(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with patch("feclora.webapi.subprocess.run", return_value=SimpleNamespace(
            returncode=0, stdout="", stderr="",
        )) as runner, patch("feclora.webapi._deployment_service_status", return_value={
            "job_id": job_id, "job_state": "created",
        }):
            result = dispatch({"action": "start_deployment_service", "params": {"job_id": job_id}})
        self.assertEqual(result["job_state"], "created")
        self.assertEqual(runner.call_args.args[0], [
            "/usr/bin/systemctl", "start", "feclora-deployment@" + job_id + ".service",
        ])

    def test_deployment_service_status_requires_canonical_uuid(self):
        with self.assertRaisesRegex(WebAPIError, "canonical UUID"):
            dispatch({"action": "deployment_service_status", "params": {"job_id": "../bad"}})

    def test_arm_deployment_job_uses_root_local_ipc(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with patch("feclora.deployment.local_control.local_control_request", return_value={
            "job_id": job_id, "accepted": True,
        }) as request:
            result = dispatch({"action": "arm_deployment_job", "params": {
                "job_id": job_id, "confirmation": "ARM " + job_id,
            }})
        self.assertTrue(result["accepted"])
        self.assertEqual(request.call_args.args[:2], ("/run/feclora/deployment.sock", "arm"))

    def test_stop_deployment_service_refuses_active_worker(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with patch("feclora.webapi._deployment_service_status", return_value={
            "job_id": job_id, "job_state": "running", "worker_active": True, "clients": [],
        }), patch("feclora.webapi.subprocess.run") as runner:
            with self.assertRaisesRegex(WebAPIError, "while a deployment worker"):
                dispatch({"action": "stop_deployment_service", "params": {"job_id": job_id}})
        runner.assert_not_called()

    def test_active_service_job_is_not_misreported_as_interrupted(self):
        import tempfile
        from pathlib import Path
        from feclora.deployment.journal import DeploymentJournal
        from feclora.deployment.coordinator import DeploymentCoordinator
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        payload = {
            "schema_version": 1, "job_id": job_id, "operation": "save",
            "image_id": "capture-1", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            journal = DeploymentJournal(Path(directory) / (job_id + ".jsonl"), job_id)
            DeploymentCoordinator(DeploymentJob.from_dict(payload), event_sink=journal)
            journal({"timestamp": "2026-11-08T12:00:00+00:00", "job_id": job_id,
                     "event": "service_started", "job_state": "created"})
            with patch("feclora.webapi.os.path.lexists", return_value=True), \
                 patch("feclora.webapi._deployment_journal_directory", return_value=Path(directory)), \
                 patch("feclora.deployment.local_control.local_control_request", return_value={"job_id": job_id}):
                jobs = dispatch({"action": "deployment_jobs"})["jobs"]
        self.assertFalse(jobs[0]["interrupted"])
        self.assertTrue(jobs[0]["service_active"])


if __name__ == "__main__":
    unittest.main()
