import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from feclora.network.remote_clone_protocol import RemoteCloneProtocolError, create_tls_context
from feclora.network.tls import accept_tls, connect_tls


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


class ServerAuthenticatedTlsTests(unittest.TestCase):
    def test_client_connects_and_verifies_exact_server_identity(self):
        raw = Mock()
        wrapped = FakeTlsSocket("source.example")
        context = Mock()
        context.wrap_socket.return_value = wrapped
        with patch("feclora.network.tls.socket.create_connection", return_value=raw):
            result = connect_tls(
                context, "source.example", 9443,
                expected_peer_identity="DNS:source.example",
            )
        self.assertIs(result, wrapped)
        context.wrap_socket.assert_called_once_with(raw, server_hostname="source.example")

    def test_client_binds_tcp_connection_to_selected_source_address(self):
        raw = Mock()
        wrapped = FakeTlsSocket("source.example")
        context = Mock()
        context.wrap_socket.return_value = wrapped
        with patch("feclora.network.tls.socket.create_connection", return_value=raw) as connect:
            result = connect_tls(
                context, "source.example", 9443,
                expected_peer_identity="DNS:source.example",
                source_address="192.0.2.20",
            )
        self.assertIs(result, wrapped)
        self.assertEqual(connect.call_args.kwargs["source_address"], ("192.0.2.20", 0))

    def test_client_rejects_route_not_using_selected_interface(self):
        context = Mock()
        route = Mock(returncode=0, stdout="192.0.2.1 dev eth0 src 192.0.2.20\n", stderr="")
        with patch("feclora.network.tls.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 9443)),
        ]):
            with patch("feclora.network.tls.subprocess.run", return_value=route):
                with patch("feclora.network.tls.socket.create_connection") as connect:
                    with self.assertRaisesRegex(OSError, "does not use selected interface"):
                        connect_tls(
                            context, "source.example", 9443,
                            expected_peer_identity="DNS:source.example",
                            source_address="192.0.2.20", network_interface="eth1",
                        )
        connect.assert_not_called()

    def test_server_accepts_tls_without_requesting_client_certificate(self):
        raw = Mock()
        wrapped = FakeTlsSocket("source.example")
        context = Mock()
        context.wrap_socket.return_value = wrapped
        result = accept_tls(context, raw)
        self.assertIs(result, wrapped)
        context.wrap_socket.assert_called_once_with(raw, server_side=True)

    def test_client_context_requires_ca_and_does_not_load_client_key(self):
        with patch("feclora.network.remote_clone_protocol.ssl.SSLContext") as factory:
            context = factory.return_value
            result = create_tls_context("client", ca_file="/ca.pem")
        self.assertIs(result, context)
        context.load_verify_locations.assert_called_once_with(cafile="/ca.pem")
        self.assertEqual(context.verify_mode, __import__("ssl").CERT_REQUIRED)
        context.load_cert_chain.assert_not_called()

    def test_client_context_rejects_client_certificate_material(self):
        with self.assertRaisesRegex(RemoteCloneProtocolError, "must not present a client certificate"):
            create_tls_context(
                "client", ca_file="/ca.pem",
                certificate_file="/client.pem", private_key_file="/client.key",
            )

    def test_server_context_does_not_request_client_certificate(self):
        with patch("feclora.network.remote_clone_protocol.ssl.SSLContext") as factory:
            context = factory.return_value
            result = create_tls_context(
                "server", certificate_file="/server.pem", private_key_file="/server.key",
            )
        self.assertIs(result, context)
        self.assertEqual(context.verify_mode, __import__("ssl").CERT_NONE)
        context.load_cert_chain.assert_called_once_with(
            certfile="/server.pem", keyfile="/server.key",
        )

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required for certificate integration test")
    def test_real_tls_server_authentication_without_client_certificate(self):
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
            server_key = os.path.join(directory, "server.key")
            server_csr = os.path.join(directory, "server.csr")
            server_cert = os.path.join(directory, "server.pem")
            ext = os.path.join(directory, "server.ext")
            with open(ext, "w", encoding="ascii") as output:
                output.write("subjectAltName=DNS:source.example\nextendedKeyUsage=serverAuth\n")
            run(
                "openssl", "req", "-newkey", "rsa:2048", "-nodes",
                "-keyout", server_key, "-out", server_csr, "-subj", "/CN=source.example",
            )
            run(
                "openssl", "x509", "-req", "-in", server_csr, "-CA", ca_cert,
                "-CAkey", ca_key, "-CAcreateserial", "-out", server_cert,
                "-days", "2", "-extfile", ext,
            )
            server_context = create_tls_context(
                "server", certificate_file=server_cert, private_key_file=server_key,
            )
            client_context = create_tls_context("client", ca_file=ca_cert)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            result = {}

            def accept():
                accepted, _address = listener.accept()
                with accept_tls(server_context, accepted) as peer:
                    result["version"] = peer.version()
                    result["client_certificate"] = peer.getpeercert()

            worker = threading.Thread(target=accept)
            worker.start()
            try:
                with connect_tls(
                    client_context, "127.0.0.1", listener.getsockname()[1],
                    expected_peer_identity="DNS:source.example",
                ) as peer:
                    self.assertIn(peer.version(), {"TLSv1.2", "TLSv1.3"})
                    self.assertIn(("DNS", "source.example"), peer.getpeercert()["subjectAltName"])
            finally:
                listener.close()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertIn(result["version"], {"TLSv1.2", "TLSv1.3"})
            self.assertIsNone(result["client_certificate"])


if __name__ == "__main__":
    unittest.main()
