import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.server_ui import run_deployment_server_ui


class PXEJobHandoffIntegrationTests(unittest.TestCase):
    def test_restore_job_publishes_and_revokes_handoff_with_actual_control_port(self):
        with tempfile.TemporaryDirectory() as journal_dir:
            config = SimpleNamespace(
                bind_address="192.0.2.10", port=9443,
                local_identity="DNS:feclora-server",
                ca_file="/etc/feclora/pki/ca.crt",
                certificate_file="/etc/feclora/pki/server.crt",
                private_key_file="/etc/feclora/pki/server.key",
                client_identity_to_mac={"URI:client-1": "02:00:00:00:00:01"},
                repository="/var/lib/feclora/images",
                server_minisign_public_key=None,
            )
            pxe_config = SimpleNamespace(
                interface="enp1s0", address="192.0.2.10",
                http_root="/srv/feclora/http", http_port=8080,
                validated=lambda: pxe_config,
            )
            job = SimpleNamespace(
                job_id="f47ac10b-58cc-4372-a567-0e02b2c3d479",
                operation="restore", image_id="gold", transport="unicast",
                authorized_clients=["02:00:00:00:00:01"],
            )
            coordinator = SimpleNamespace(
                clients=lambda: [],
                state=SimpleNamespace(value="created"),
            )

            class FakeControl:
                listener_errors = []
                def __init__(self, *_args, **_kwargs):
                    self.stopped = False
                def start(self, _address, _port):
                    return "192.0.2.10", 9555
                def stop(self):
                    self.stopped = True

            with patch("feclora.deployment.server_ui.ensure_server_deployment_config", return_value=False), \
                 patch("feclora.deployment.server_ui.load_server_runtime_config", return_value=config), \
                 patch("feclora.deployment.server_ui._manage_client_enrollment"), \
                 patch("feclora.deployment.server_ui._journal_directory", return_value=journal_dir), \
                 patch("feclora.deployment.server_ui._review_previous_journals"), \
                 patch("feclora.deployment.server_ui._choose_job", return_value=(job, None, ["02:00:00:00:00:01"])), \
                 patch("feclora.deployment.server_ui.create_mutual_tls_context", return_value=object()), \
                 patch("feclora.deployment.server_ui.DeploymentJournal"), \
                 patch("feclora.deployment.server_ui.DeploymentCoordinator", return_value=coordinator), \
                 patch("feclora.deployment.server_ui.DeploymentControlServer", FakeControl), \
                 patch("feclora.deployment.server_ui.publish_unattended_ipxe_script") as publish, \
                 patch("feclora.deployment.server_ui.revoke_unattended_ipxe_script") as revoke, \
                 patch("feclora.deployment.server_ui.dialog_app._message"), \
                 patch("feclora.deployment.server_ui.dialog_app._menu", return_value="stop"):
                result = run_deployment_server_ui(
                    "enp1s0", "192.0.2.10", firewall=object(), pxe_config=pxe_config,
                )

            self.assertEqual(result, 0)
            publish.assert_called_once_with(
                "/srv/feclora/http", "192.0.2.10",
                "f47ac10b-58cc-4372-a567-0e02b2c3d479", 8080, 9555,
            )
            revoke.assert_called_once_with(
                "/srv/feclora/http", "192.0.2.10",
                "f47ac10b-58cc-4372-a567-0e02b2c3d479", 8080, 9555,
            )

    def test_save_job_does_not_publish_unattended_restore_handoff(self):
        with tempfile.TemporaryDirectory() as journal_dir:
            config = SimpleNamespace(
                bind_address="192.0.2.10", port=9443,
                local_identity="DNS:feclora-server",
                client_identity_to_mac={"URI:client-1": "02:00:00:00:00:01"},
                repository="/var/lib/feclora/images",
                server_minisign_public_key=None,
            )
            pxe_config = SimpleNamespace(
                interface="enp1s0", address="192.0.2.10",
                http_root="/srv/feclora/http", http_port=8080,
                validated=lambda: pxe_config,
            )
            job = SimpleNamespace(
                job_id="f47ac10b-58cc-4372-a567-0e02b2c3d479",
                operation="save", image_id="capture", transport="unicast",
                authorized_clients=["02:00:00:00:00:01"],
            )
            coordinator = SimpleNamespace(
                clients=lambda: [],
                state=SimpleNamespace(value="created"),
            )

            class FakeControl:
                listener_errors = []
                def __init__(self, *_args, **_kwargs):
                    pass
                def start(self, _address, _port):
                    return "192.0.2.10", 9555
                def stop(self):
                    pass

            with patch("feclora.deployment.server_ui.ensure_server_deployment_config", return_value=False), \
                 patch("feclora.deployment.server_ui.load_server_runtime_config", return_value=config), \
                 patch("feclora.deployment.server_ui._manage_client_enrollment"), \
                 patch("feclora.deployment.server_ui._journal_directory", return_value=journal_dir), \
                 patch("feclora.deployment.server_ui._review_previous_journals"), \
                 patch("feclora.deployment.server_ui._choose_job", return_value=(job, None, ["02:00:00:00:00:01"])), \
                 patch("feclora.deployment.server_ui.create_mutual_tls_context", return_value=object()), \
                 patch("feclora.deployment.server_ui.DeploymentJournal"), \
                 patch("feclora.deployment.server_ui.DeploymentCoordinator", return_value=coordinator), \
                 patch("feclora.deployment.server_ui.DeploymentControlServer", FakeControl), \
                 patch("feclora.deployment.server_ui.publish_unattended_ipxe_script") as publish, \
                 patch("feclora.deployment.server_ui.revoke_unattended_ipxe_script") as revoke, \
                 patch("feclora.deployment.server_ui.dialog_app._message"), \
                 patch("feclora.deployment.server_ui.dialog_app._menu", return_value="stop"):
                result = run_deployment_server_ui(
                    "enp1s0", "192.0.2.10", firewall=object(), pxe_config=pxe_config,
                )

            self.assertEqual(result, 0)
            publish.assert_not_called()
            revoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
