import threading
import unittest
from unittest.mock import patch

from feclora.deployment.control import DeploymentControlError, DeploymentControlServer


class AcceptedSocket:
    def settimeout(self, _value):
        pass

    def close(self):
        raise OSError("TLS socket already closed")


class HandshakeCleanupTests(unittest.TestCase):
    def test_tls_close_failure_does_not_mask_handshake_error_or_leak_pending_socket(self):
        accepted = object()
        tls_socket = AcceptedSocket()
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server._lock = threading.RLock()
        server._pending_sockets = set()
        server._stop_event = threading.Event()
        server.tls_context = object()
        listener = type(
            "Listener", (),
            {"accept": lambda _self: (accepted, ("192.0.2.10", 40000))},
        )()

        with (
            patch("feclora.deployment.control.accept_tls", return_value=tls_socket),
            patch(
                "feclora.deployment.control.receive_control_message",
                side_effect=DeploymentControlError("malformed hello"),
            ),
        ):
            with self.assertRaisesRegex(DeploymentControlError, "malformed hello"):
                server.accept_ready_client(listener)

        self.assertEqual(server._pending_sockets, set())


    def test_accepted_socket_close_failure_does_not_mask_tls_handshake_error(self):
        class AcceptedCloseFailureSocket:
            def settimeout(self, _value):
                pass

            def close(self):
                raise OSError("accepted socket already closed")

        accepted = AcceptedCloseFailureSocket()
        server = DeploymentControlServer.__new__(DeploymentControlServer)
        server._lock = threading.RLock()
        server._pending_sockets = set()
        server._stop_event = threading.Event()
        server.tls_context = object()
        listener = type(
            "Listener", (),
            {"accept": lambda _self: (accepted, ("192.0.2.10", 40000))},
        )()

        with patch(
            "feclora.deployment.control.accept_tls",
            side_effect=DeploymentControlError("TLS negotiation failed"),
        ):
            with self.assertRaisesRegex(DeploymentControlError, "TLS negotiation failed"):
                server.accept_ready_client(listener)

        self.assertEqual(server._pending_sockets, set())


if __name__ == "__main__":
    unittest.main()
