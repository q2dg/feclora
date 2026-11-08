import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from feclora.webapi import WebAPIError, dispatch, _device, _server_trusted_clients, _revoke_server_client
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

    def test_server_trusted_clients_action_returns_public_inventory(self):
        expected = {"clients": [{
            "identity": "URI:feclora-client-lab",
            "mac_address": "52:54:00:12:34:56",
            "image_capture": True,
        }]}
        with patch("feclora.webapi._server_trusted_clients", return_value=expected) as inventory:
            self.assertEqual(dispatch({"action": "server_trusted_clients"}), expected)
        inventory.assert_called_once_with()
        with self.assertRaisesRegex(WebAPIError, "does not accept parameters"):
            dispatch({"action": "server_trusted_clients", "params": {"private_key": "no"}})

    def test_revoke_server_client_requires_exact_confirmation_and_is_allowlisted(self):
        identity = "URI:feclora-client-lab"
        with self.assertRaisesRegex(WebAPIError, "confirmation does not match"):
            dispatch({"action": "revoke_server_client", "params": {
                "identity": identity, "confirmation": "REVOKE someone-else",
            }})
        with patch("feclora.webapi._revoke_server_client", return_value={
            "identity": identity, "mac_address": "52:54:00:12:34:56", "revoked": True,
        }) as revoke:
            result = dispatch({"action": "revoke_server_client", "params": {
                "identity": identity, "confirmation": f"REVOKE {identity}",
            }})
        revoke.assert_called_once_with({
            "identity": identity, "confirmation": f"REVOKE {identity}",
        })
        self.assertTrue(result["revoked"])

    def test_server_trusted_clients_reads_only_public_runtime_fields(self):
        config = SimpleNamespace(
            client_identity_to_mac={
                "URI:feclora-client-b": "52:54:00:00:00:02",
                "URI:feclora-client-a": "52:54:00:00:00:01",
            },
            client_minisign_public_keys={"52:54:00:00:00:02": "public-key"},
        )
        with (
            patch("os.path.isfile", return_value=True),
            patch("feclora.deployment.runtime_config.load_server_runtime_config", return_value=config) as load,
        ):
            result = _server_trusted_clients()
        load.assert_called_once_with("/etc/feclora/deployment-server.json")
        self.assertEqual(result, {"clients": [
            {"identity": "URI:feclora-client-a", "mac_address": "52:54:00:00:00:01", "image_capture": False},
            {"identity": "URI:feclora-client-b", "mac_address": "52:54:00:00:00:02", "image_capture": True},
        ]})
        self.assertNotIn("private_key", repr(result))

    def test_revoke_server_client_invokes_managed_revocation_with_exact_phrase(self):
        identity = "URI:feclora-client-lab"
        with patch("feclora.deployment.enrollment.revoke_client_certificate", return_value="52:54:00:12:34:56") as revoke:
            result = _revoke_server_client({
                "identity": identity, "confirmation": f"REVOKE {identity}",
            })
        revoke.assert_called_once_with(
            "/etc/feclora/deployment-server.json", identity,
            confirmation=f"REVOKE {identity}",
        )
        self.assertEqual(result, {
            "identity": identity, "mac_address": "52:54:00:12:34:56", "revoked": True,
        })

    def test_revoke_server_client_rejects_extra_fields_and_invalid_identity(self):
        with self.assertRaisesRegex(WebAPIError, "exactly identity and confirmation"):
            _revoke_server_client({"identity": "URI:feclora-client-lab", "confirmation": "REVOKE URI:feclora-client-lab", "extra": True})
        with self.assertRaisesRegex(WebAPIError, "identity is invalid"):
            _revoke_server_client({"identity": "URI:other", "confirmation": "REVOKE URI:other"})

    def test_revoke_server_client_wraps_managed_pki_errors(self):
        identity = "URI:feclora-client-lab"
        with patch("feclora.deployment.enrollment.revoke_client_certificate", side_effect=RuntimeError("inventory corrupt")):
            with self.assertRaisesRegex(WebAPIError, "Client revocation failed: inventory corrupt"):
                _revoke_server_client({"identity": identity, "confirmation": f"REVOKE {identity}"})

    def test_partition_extraction_verifies_disk_type_and_publishes_new_manifest(self):
        from pathlib import Path
        manifest = SimpleNamespace(
            image_type="disk",
            artifacts=[SimpleNamespace(encryption="none")],
        )
        extracted = SimpleNamespace(image_id="source-part-abc123", image_type="partition")
        with patch("feclora.webapi._image_manifest", return_value=Path("/repo/source.manifest.json")), patch(
            "feclora.webapi.ImageManifest.from_json", return_value=manifest
        ), patch("feclora.webapi.os.path.isfile", return_value=False), patch(
            "feclora.webapi._security_material",
            return_value={"age_decryption_available": False, "image_verification_available": False, "image_signing_available": False},
        ), patch("feclora.webapi._client_runtime_config", return_value=None), patch(
            "feclora.webapi._capture_material", return_value=(None, None)
        ), patch("feclora.webapi._repository", return_value=Path("/repo")), patch(
            "feclora.storage.disk_image_partition.extract_partition_image",
            return_value=(extracted, "source-part-abc123.manifest.json"),
        ) as extract:
            result = __import__("feclora.webapi", fromlist=["_execute_operation"])._execute_operation(
                "extract_partition_image", {"image_id": "source", "selector": "PARTUUID=abc"}, "operation-1"
            )
        self.assertEqual(result["image_id"], "source-part-abc123")
        self.assertFalse(result["signed"])
        self.assertEqual(result["source_image_id"], "source")
        extract.assert_called_once()

    def test_partition_extraction_is_exposed_as_a_storage_operation(self):
        params = {"image_id": "whole-disk", "selector": "PARTUUID=abc"}
        with patch("feclora.webapi._run_operation", return_value={"image_id": "whole-disk-part-123"}) as run:
            result = dispatch({"action": "extract_partition_image", "params": params})
        run.assert_called_once_with("extract_partition_image", params)
        self.assertEqual(result["image_id"], "whole-disk-part-123")

    def test_age_recipient_export_and_refresh_actions_are_allowlisted(self):
        with patch("feclora.deployment.cockpit_enrollment.export_server_age_recipients",
                   return_value={"recipient_count": 2}) as export:
            self.assertEqual(dispatch({"action": "export_server_age_recipients", "params": {
                "export_directory": "/run/media/usb",
            }}), {"recipient_count": 2})
        export.assert_called_once_with({"export_directory": "/run/media/usb"})
        with patch("feclora.deployment.cockpit_client.refresh_client_age_recipients",
                   return_value={"recipient_count": 2}) as refresh:
            self.assertEqual(dispatch({"action": "refresh_client_age_recipients", "params": {
                "inventory_path": "/run/media/usb/age-recipients.txt",
            }}), {"recipient_count": 2})
        refresh.assert_called_once_with({"inventory_path": "/run/media/usb/age-recipients.txt"})

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

    def test_start_deployment_service_accepts_fresh_multicast_restore_journal(self):
        import tempfile
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        journal = SimpleNamespace(recovery_report=lambda: {
            "job_id": job_id, "job": {"transport": "multicast"},
            "job_state": "created", "interrupted": False,
        })
        status = {"job_id": job_id, "job_state": "created", "worker_active": False}
        with tempfile.TemporaryDirectory() as directory, patch(
            "feclora.webapi._active_deployment_service_status", return_value=None
        ), patch(
            "feclora.webapi._deployment_journal_directory", return_value=Path(directory)
        ), patch("feclora.deployment.journal.DeploymentJournal.inspect", return_value=journal), patch(
            "feclora.webapi.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")
        ) as runner, patch("feclora.webapi._deployment_service_status", return_value=status):
            result = dispatch({"action": "start_deployment_service", "params": {"job_id": job_id}})
        self.assertEqual(result, status)
        self.assertEqual(runner.call_args.args[0], [
            "/usr/bin/systemctl", "start", "feclora-deployment@" + job_id + ".service",
        ])

    def test_start_deployment_service_reconnects_to_active_job_without_revalidating_freshness(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        status = {"job_id": job_id, "job_state": "running", "worker_active": True}
        with patch("feclora.webapi._active_deployment_service_status", return_value=status), patch(
            "feclora.webapi.subprocess.run"
        ) as run:
            result = dispatch({"action": "start_deployment_service", "params": {"job_id": job_id}})
        self.assertEqual(result, status)
        run.assert_not_called()

    def test_create_deployment_job_reaches_server_validation_for_multicast(self):
        from feclora.deployment.runtime_config import RuntimeConfigError
        payload = {
            "schema_version": 1, "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
            "operation": "restore", "image_id": "lab-image", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
            "network_interface": "enp1s0", "transport": "multicast",
            "multicast_group": "239.10.10.10", "multicast_port": 9000,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with patch(
            "feclora.deployment.runtime_config.load_server_runtime_config",
            side_effect=RuntimeConfigError("test Server config"),
        ):
            with self.assertRaisesRegex(WebAPIError, "configure the Feclora Server"):
                dispatch({"action": "create_deployment_job", "params": {"job": payload}})

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
        import tempfile
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        journal = SimpleNamespace(recovery_report=lambda: {
            "job_id": job_id, "job_state": "created", "interrupted": False,
            "job": {"transport": "unicast"},
        })
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / f"{job_id}.jsonl").write_text("journal\n", encoding="utf-8")
            with patch("feclora.webapi._deployment_journal_directory", return_value=Path(directory)), \
                 patch("feclora.deployment.journal.DeploymentJournal.inspect", return_value=journal), \
                 patch("feclora.webapi.subprocess.run", return_value=SimpleNamespace(
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

    def test_reconcile_rejects_a_job_owned_by_the_live_service(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with patch("feclora.deployment.local_control.local_control_request", return_value={
            "job_id": job_id, "job_state": "created",
        }):
            with self.assertRaisesRegex(WebAPIError, "stop the active deployment service"):
                dispatch({"action": "reconcile_deployment_job", "params": {
                    "job_id": job_id, "confirmation": "RECONCILE " + job_id,
                }})

    def test_create_unicast_job_rejects_multiple_clients(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        job = {
            "schema_version": 1, "job_id": job_id, "operation": "save",
            "image_id": "capture-1", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        }
        with self.assertRaisesRegex(WebAPIError, "exactly one Client"):
            dispatch({"action": "create_deployment_job", "params": {"job": job}})

    def test_pxe_start_refuses_to_replace_active_deployment_firewall_zone(self):
        params = {
            "interface": "enp1s0", "address": "192.0.2.1", "prefix_length": 24,
            "mode": "proxy", "pool_start": "192.0.2.100", "pool_end": "192.0.2.150",
            "lease_time": "1h", "gateway": "", "dns_server": "192.0.2.1",
            "http_port": 8080, "authoritative_confirmed": False,
        }
        with patch("feclora.webapi._validate_pxe_profile"), \
             patch("feclora.network.pxe_config.PXENetworkConfig", return_value=SimpleNamespace(interface="enp1s0")), \
             patch("feclora.webapi._active_deployment_service_status", return_value={
                 "network_interface": "enp1s0",
             }), patch("feclora.webapi._pxe_service_manager") as manager:
            with self.assertRaisesRegex(WebAPIError, "active deployment service"):
                dispatch({"action": "start_pxe_services", "params": params})
        manager.assert_not_called()

    def test_pxe_stop_refuses_to_remove_active_deployment_firewall_zone(self):
        manager = SimpleNamespace(status=lambda: {
            "active": True, "interface": "enp1s0",
        }, stop=Mock())
        with patch("feclora.webapi._pxe_service_manager", return_value=manager), \
             patch("feclora.webapi._active_deployment_service_status", return_value={
                 "network_interface": "enp1s0",
             }):
            with self.assertRaisesRegex(WebAPIError, "stop the deployment service"):
                dispatch({"action": "stop_pxe_services"})
        manager.stop.assert_not_called()

    def test_inspect_remote_job_uses_enrolled_mtls_client_identity(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        job = DeploymentJob.from_dict({
            "schema_version": 1, "job_id": job_id, "operation": "restore",
            "image_id": "golden-image", "target_type": "disk",
            "authorized_clients": ["52:54:00:12:34:56"],
            "network_interface": "enp1s0", "transport": "unicast",
            "multicast_group": None, "multicast_port": None,
            "start_policy": "manual", "expected_clients": None, "start_deadline": None,
        })
        config = SimpleNamespace(
            host="192.0.2.10", port=9443, local_identity="URI:feclora-client-1",
            server_identity="URI:feclora-server", mac_address="52:54:00:12:34:56",
            ca_file="/etc/feclora/pki/ca.crt", certificate_file="/etc/feclora/pki/client.crt",
            private_key_file="/etc/feclora/pki/client.key", age_identity_file=None,
            age_recipients_file=None, local_minisign_secret_key=None,
        )
        with patch("feclora.deployment.runtime_config.load_client_runtime_config", return_value=config), \
             patch("feclora.network.remote_clone_protocol.create_mutual_tls_context", return_value=object()), \
             patch("feclora.deployment.control.inspect_deployment_job", return_value=job) as inspect:
            result = dispatch({"action": "inspect_remote_job", "params": {
                "host": "", "job_id": job_id,
            }})
        self.assertEqual(result["job"]["job_id"], job_id)
        self.assertEqual(result["host"], "192.0.2.10")
        self.assertEqual(inspect.call_args.args[0], "192.0.2.10")
        self.assertEqual(inspect.call_args.kwargs["mac_address"], config.mac_address)

    def test_start_client_job_persists_private_request_and_starts_systemd_unit(self):
        import stat
        import tempfile
        from pathlib import Path
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_lstat = os.lstat
            with patch("feclora.webapi._inspect_remote_job", return_value={
                "host": "192.0.2.10", "server_identity": "URI:server",
                "job": {"job_id": job_id, "operation": "restore", "target_type": "disk", "transport": "unicast"},
            }), patch("feclora.webapi._client_job_directory", return_value=root), \
                 patch("feclora.storage.inventory.collect_inventory", return_value={
                     "devices": [{"type": "disk", "path": "/dev/sda", "children": []}],
                 }), patch("feclora.webapi.os.lstat", side_effect=lambda path: block_info if os.fspath(path) == "/dev/sda" else real_lstat(path)), \
                 patch("feclora.webapi.subprocess.run", return_value=SimpleNamespace(
                     returncode=0, stdout="", stderr="",
                 )) as runner, patch("feclora.webapi._client_job_status", return_value={
                     "job_id": job_id, "phase": "connecting",
                 }):
                result = dispatch({"action": "start_client_job", "params": {
                    "host": "192.0.2.10", "job_id": job_id, "device_path": "/dev/sda",
                    "confirmation": "ERASE /dev/sda FROM URI:server", "compression": "gzip",
                    "network_interface": None,
                    "igmp_confirmed": False,
                }})
            request = json.loads((root / (job_id + ".request.json")).read_text(encoding="utf-8"))
        self.assertEqual(result["phase"], "connecting")
        self.assertEqual(request["device_path"], "/dev/sda")
        self.assertIsNone(request["network_interface"])
        self.assertFalse(request["igmp_confirmed"])
        self.assertEqual(runner.call_args.args[0], [
            "/usr/bin/systemctl", "start", "feclora-client@" + job_id + ".service",
        ])

    def test_start_client_job_preflights_and_persists_multicast_interface(self):
        import stat
        import tempfile
        from pathlib import Path
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            block_info = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)
            real_lstat = os.lstat
            preflight = SimpleNamespace(
                interface="enp1s0", ipv4_address="192.0.2.20",
                warnings=("Verify IGMP snooping and querier.",),
            )
            with patch("feclora.webapi._inspect_remote_job", return_value={
                "host": "192.0.2.10", "server_identity": "URI:server",
                "job": {
                    "job_id": job_id, "operation": "restore", "target_type": "disk",
                    "transport": "multicast", "multicast_group": "239.10.10.10",
                },
            }), patch("feclora.webapi.socket.if_nameindex", return_value=[(2, "enp1s0")]), \
                 patch("feclora.network.multicast_preflight.inspect_multicast_interface", return_value=preflight) as inspect, \
                 patch("feclora.webapi._client_job_directory", return_value=root), \
                 patch("feclora.storage.inventory.collect_inventory", return_value={
                     "devices": [{"type": "disk", "path": "/dev/sda", "children": []}],
                 }), patch("feclora.webapi.os.lstat",
                           side_effect=lambda path: block_info if os.fspath(path) == "/dev/sda" else real_lstat(path)), \
                 patch("feclora.webapi.subprocess.run", return_value=SimpleNamespace(
                     returncode=0, stdout="", stderr="",
                 )), patch("feclora.webapi._client_job_status", return_value={
                     "job_id": job_id, "phase": "connecting",
                 }):
                result = dispatch({"action": "start_client_job", "params": {
                    "host": "192.0.2.10", "job_id": job_id, "device_path": "/dev/sda",
                    "confirmation": "ERASE /dev/sda FROM URI:server", "compression": "gzip",
                    "network_interface": "enp1s0",
                    "igmp_confirmed": True,
                }})
            request = json.loads((root / (job_id + ".request.json")).read_text(encoding="utf-8"))
        inspect.assert_called_once_with("enp1s0", "239.10.10.10", role="receiver")
        self.assertEqual(request["network_interface"], "enp1s0")
        self.assertTrue(request["igmp_confirmed"])
        self.assertEqual(result["multicast_preflight"]["warnings"], list(preflight.warnings))

    def test_client_job_status_marks_nonterminal_inactive_service_interrupted(self):
        job_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        with patch("feclora.webapi._client_job_paths", return_value=(Path("/tmp/request"), Path("/tmp/status"))), \
             patch("feclora.webapi._read_client_job_status", return_value={
                 "job_id": job_id, "phase": "running",
             }), patch("feclora.webapi.subprocess.run", return_value=SimpleNamespace(returncode=3)):
            result = dispatch({"action": "client_job_status", "params": {"job_id": job_id}})
        self.assertFalse(result["unit_active"])
        self.assertTrue(result["interrupted"])


if __name__ == "__main__":
    unittest.main()
