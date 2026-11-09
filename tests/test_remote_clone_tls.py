import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from feclora.network.remote_clone_protocol import create_mutual_tls_context
from feclora.network.tls import accept_mutual_tls, connect_mutual_tls


class FakeTlsSocket:
    def __init__(self, peer):
        self.peer = peer
        self.closed = False

    def getpeercert(self, binary_form=False):
        return b"certificate" if binary_form else {"subjectAltName": (("DNS", self.peer),)}

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class MutualTlsSocketTests(unittest.TestCase):
    def test_client_connects_and_verifies_exact_peer(self):
        raw = Mock()
        wrapped = FakeTlsSocket("source.example")
        context = Mock()
        context.wrap_socket.return_value = wrapped
        with patch("feclora.network.tls.socket.create_connection", return_value=raw):
            result = connect_mutual_tls(
                context, "source.example", 9443,
                expected_peer_identity="DNS:source.example",
            )
        self.assertIs(result, wrapped)
        context.wrap_socket.assert_called_once_with(raw, server_hostname="source.example")

    def test_client_cancels_before_attempting_tcp_connection(self):
        from feclora.network.remote_clone_protocol import RemoteCloneCancelled

        context = Mock()
        with patch("feclora.network.tls.socket.create_connection") as connect:
            with self.assertRaisesRegex(RemoteCloneCancelled, "while connecting"):
                connect_mutual_tls(
                    context, "source.example", 9443,
                    expected_peer_identity="DNS:source.example",
                    cancel_check=lambda: True,
                )
        connect.assert_not_called()

    def test_client_retries_tcp_timeout_and_checks_cancellation(self):
        from feclora.network.remote_clone_protocol import RemoteCloneCancelled

        raw = Mock()
        context = Mock()
        checks = []

        def cancelled():
            checks.append(True)
            return len(checks) > 1

        with patch(
            "feclora.network.tls.socket.create_connection",
            side_effect=[socket.timeout(), raw],
        ) as connect:
            with self.assertRaisesRegex(RemoteCloneCancelled, "while connecting"):
                connect_mutual_tls(
                    context, "source.example", 9443,
                    expected_peer_identity="DNS:source.example",
                    cancel_check=cancelled,
                    connect_poll_interval=0.05,
                )
        self.assertEqual(connect.call_count, 1)
        context.wrap_socket.assert_not_called()

    def test_server_wraps_and_verifies_client_certificate(self):
        raw = Mock()
        wrapped = FakeTlsSocket("receiver.example")
        context = Mock()
        context.wrap_socket.return_value = wrapped
        result = accept_mutual_tls(
            context, raw, expected_peer_identity="DNS:receiver.example",
        )
        self.assertIs(result, wrapped)
        context.wrap_socket.assert_called_once_with(raw, server_side=True)

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required for certificate integration test")
    def test_real_tls13_mutual_authentication_and_san_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(*args):
                subprocess.run(args, check=True, capture_output=True, text=True)

            ca_key = os.path.join(directory, "ca.key")
            ca_cert = os.path.join(directory, "ca.pem")
            run(
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", ca_key, "-out", ca_cert, "-days", "2",
                "-subj", "/CN=feclora-test-ca",
            )

            def issue(name, san, eku):
                key = os.path.join(directory, name + ".key")
                csr = os.path.join(directory, name + ".csr")
                cert = os.path.join(directory, name + ".pem")
                ext = os.path.join(directory, name + ".ext")
                with open(ext, "w", encoding="ascii") as output:
                    output.write(f"subjectAltName=DNS:{san}\nextendedKeyUsage={eku}\n")
                run(
                    "openssl", "req", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key, "-out", csr, "-subj", f"/CN={san}",
                )
                run(
                    "openssl", "x509", "-req", "-in", csr, "-CA", ca_cert,
                    "-CAkey", ca_key, "-CAcreateserial", "-out", cert,
                    "-days", "2", "-extfile", ext,
                )
                return cert, key

            source_cert, source_key = issue("source", "source.example", "serverAuth")
            receiver_cert, receiver_key = issue("receiver", "receiver.example", "clientAuth")
            server_context = create_mutual_tls_context(
                "server", ca_file=ca_cert,
                certificate_file=source_cert, private_key_file=source_key,
            )
            client_context = create_mutual_tls_context(
                "client", ca_file=ca_cert,
                certificate_file=receiver_cert, private_key_file=receiver_key,
            )
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            result = {}

            def accept():
                accepted, _address = listener.accept()
                with accept_mutual_tls(
                    server_context, accepted,
                    expected_peer_identity="DNS:receiver.example",
                ) as peer:
                    result["server_version"] = peer.version()
                    result["client_identity"] = peer.getpeercert()["subjectAltName"]

            worker = threading.Thread(target=accept)
            worker.start()
            try:
                with connect_mutual_tls(
                    client_context, "127.0.0.1", listener.getsockname()[1],
                    expected_peer_identity="DNS:source.example",
                ) as peer:
                    self.assertEqual(peer.version(), "TLSv1.3")
                    self.assertIn(("DNS", "source.example"), peer.getpeercert()["subjectAltName"])
            finally:
                listener.close()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result["server_version"], "TLSv1.3")
            self.assertIn(("DNS", "receiver.example"), result["client_identity"])

    def test_client_closes_raw_socket_when_peer_identity_is_wrong(self):
        raw = Mock()
        context = Mock()
        context.wrap_socket.return_value = FakeTlsSocket("attacker.example")
        with patch("feclora.network.tls.socket.create_connection", return_value=raw):
            with self.assertRaisesRegex(Exception, "exact SAN identity"):
                connect_mutual_tls(
                    context, "source.example", 9443,
                    expected_peer_identity="DNS:source.example",
                )
        raw.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
