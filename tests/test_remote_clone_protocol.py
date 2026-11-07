import hashlib
import io
import json
import socket
import struct
import unittest
from types import SimpleNamespace

from feclora.network.remote_clone_protocol import (
    CloneSessionHeader,
    CloneStreamResult,
    RemoteCloneCancelled,
    RemoteCloneProtocolError,
    receive_disk_stream,
    receive_session_header,
    send_disk_stream,
    send_session_header,
    verify_peer_identity,
)


class RemoteCloneProtocolTests(unittest.TestCase):
    def setUp(self):
        self.header = CloneSessionHeader(
            session_id="7a3c4c12-6a88-4f0d-bcc0-90df80a4adf1",
            source_identity="DNS:source.example",
            receiver_identity="DNS:receiver.example",
            source_device="/dev/sda",
            source_size_bytes=128 * 1024,
            logical_sector_size=512,
            chunk_size_bytes=64 * 1024,
        )

    def test_session_header_round_trip(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_session_header(left, self.header)
        self.assertEqual(receive_session_header(right), self.header)

    def test_rejects_unknown_header_fields(self):
        value = self.header.to_dict()
        value["unexpected"] = True
        with self.assertRaisesRegex(RemoteCloneProtocolError, "unknown fields"):
            CloneSessionHeader.from_dict(value)

    def test_rejects_duplicate_json_fields(self):
        payload = b'{"schema_version":1,"schema_version":1}'
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.sendall(struct.pack("!I", len(payload)) + payload)
        with self.assertRaisesRegex(RemoteCloneProtocolError, "duplicate JSON field"):
            receive_session_header(right)

    def test_stream_transfer_checks_digest_and_byte_count(self):
        payload = b"feclora-remote-clone" * 7000
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        source = io.BytesIO(payload)
        destination = io.BytesIO()
        sent = send_disk_stream(left, source, len(payload), session_id=self.header.session_id, chunk_size=64 * 1024)
        received = receive_disk_stream(right, destination, len(payload), session_id=self.header.session_id, chunk_size=64 * 1024)
        self.assertEqual(sent, received)
        self.assertEqual(destination.getvalue(), payload)
        self.assertEqual(received.sha256, hashlib.sha256(payload).hexdigest())

    def test_rejects_digest_mismatch(self):
        payload = b"disk-data"
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.sendall(payload)
        wrong = CloneStreamResult(self.header.session_id, len(payload), "0" * 64)
        encoded = json.dumps(wrong.to_dict(), separators=(",", ":")).encode("ascii")
        left.sendall(struct.pack("!I", len(encoded)) + encoded)
        with self.assertRaisesRegex(RemoteCloneProtocolError, "digests differ"):
            receive_disk_stream(right, io.BytesIO(), len(payload), session_id=self.header.session_id, chunk_size=64 * 1024)

    def test_rejects_short_source_stream(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        with self.assertRaisesRegex(RemoteCloneProtocolError, "ended before"):
            send_disk_stream(left, io.BytesIO(b"short"), 10, session_id=self.header.session_id, chunk_size=64 * 1024)

    def test_cancellation_is_explicit(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        with self.assertRaises(RemoteCloneCancelled):
            send_disk_stream(
                left, io.BytesIO(b"x" * 100), 100, session_id=self.header.session_id, chunk_size=64 * 1024,
                cancel_check=lambda: True,
            )

    def test_peer_identity_accepts_exact_san(self):
        class FakeTlsSocket:
            def getpeercert(self, binary_form=False):
                if binary_form:
                    return b"test certificate bytes"
                return {"subjectAltName": (("DNS", "source.example"),)}
        verify_peer_identity(FakeTlsSocket(), "DNS:source.example")
        with self.assertRaisesRegex(RemoteCloneProtocolError, "exact SAN"):
            verify_peer_identity(FakeTlsSocket(), "DNS:other.example")

    def test_peer_identity_accepts_sha256_pin(self):
        certificate = b"pinned certificate"
        fingerprint = hashlib.sha256(certificate).hexdigest()
        class FakeTlsSocket:
            def getpeercert(self, binary_form=False):
                return certificate if binary_form else {}
        verify_peer_identity(FakeTlsSocket(), "sha256:" + fingerprint)


if __name__ == "__main__":
    unittest.main()
