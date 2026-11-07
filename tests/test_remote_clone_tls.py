import unittest
from unittest.mock import Mock, patch

from feclora.network.tls import accept_mutual_tls, connect_mutual_tls


class FakeTlsSocket:
    def __init__(self, peer):
        self.peer = peer
        self.closed = False

    def getpeercert(self, binary_form=False):
        return b"certificate" if binary_form else {"subjectAltName": (("DNS", self.peer),)}

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
