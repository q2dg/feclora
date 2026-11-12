import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feclora.deployment.server_ui import run_deployment_server_ui


class PXEJobHandoffIntegrationTests(unittest.TestCase):
    def test_legacy_mtls_job_ui_does_not_publish_per_client_pxe_handoff(self):
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
                target_type="disk", target_bindings=(),
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
                 patch("feclora.deployment.server_ui._journal_directory", return_value=journal_dir), \
                 patch("feclora.deployment.server_ui._review_previous_journals"), \
                 patch("feclora.deployment.server_ui._choose_job", return_value=(job, None, ["02:00:00:00:00:01"])), \
                 patch("feclora.deployment.server_ui.create_tls_context", return_value=object()), \
                 patch("feclora.deployment.server_ui.DeploymentJournal"), \
                 patch("feclora.deployment.server_ui.DeploymentCoordinator", return_value=coordinator), \
                 patch("feclora.deployment.server_ui.DeploymentControlServer", FakeControl), \
                 patch("feclora.deployment.server_ui.dialog_app._message") as message, \
                 patch("feclora.deployment.server_ui.dialog_app._menu", return_value="stop"):
                result = run_deployment_server_ui(
                    "enp1s0", "192.0.2.10", firewall=object(), pxe_config=pxe_config,
                )

            self.assertEqual(result, 0)
            rendered_messages = "\n".join(str(call.args) for call in message.call_args_list)
            self.assertNotIn("FECLORA-CLIENT", rendered_messages)
            self.assertNotIn("unattended PXE handoff script", rendered_messages)
            self.assertNotIn("target binding required", rendered_messages)


if __name__ == "__main__":
    unittest.main()
