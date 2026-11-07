import hashlib
import io
import json
import socket
import struct
import unittest
from types import SimpleNamespace

from feclora.network.remote_clone_protocol import (
    CloneSessionHeader,
    CloneSessionReady,
    CloneStreamResult,
    CloneVerificationResult,
    authorize_endpoint,
    receive_session_ready,
    receive_verification_result,
    send_session_ready,
    send_verification_result,
    validate_endpoint_authorization,
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
            receiver_target_device="/dev/sdb",
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

    def test_endpoint_authorization_is_role_and_device_specific(self):
        source = authorize_endpoint(
            self.header, role="source",
            local_identity="DNS:source.example",
            expected_peer_identity="DNS:receiver.example",
            confirmation="READ /dev/sda TO DNS:receiver.example",
        )
        receiver = authorize_endpoint(
            self.header, role="receiver",
            local_identity="DNS:receiver.example",
            expected_peer_identity="DNS:source.example",
            confirmation="ERASE /dev/sdb FROM DNS:source.example",
        )
        validate_endpoint_authorization(source, self.header, role="source", device_path="/dev/sda")
        validate_endpoint_authorization(receiver, self.header, role="receiver", device_path="/dev/sdb")
        with self.assertRaisesRegex(RemoteCloneProtocolError, "explicit receiver authorization"):
            authorize_endpoint(
                self.header, role="receiver",
                local_identity="DNS:receiver.example",
                expected_peer_identity="DNS:source.example",
                confirmation="yes",
            )

    def test_verification_result_rejects_non_string_status(self):
        value = {
            "session_id": self.header.session_id,
            "status": [],
            "byte_count": 10,
            "stream_sha256": "a" * 64,
            "readback_sha256": "a" * 64,
            "error": None,
        }
        with self.assertRaisesRegex(RemoteCloneProtocolError, "status must be"):
            CloneVerificationResult.from_dict(value)

    def test_receiver_verification_ack_is_session_bound(self):
        digest = hashlib.sha256(b"verified disk").hexdigest()
        result = CloneVerificationResult(
            self.header.session_id, "verified", len(b"verified disk"), digest, digest,
        )
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_verification_result(left, result)
        received = receive_verification_result(
            right, session_id=self.header.session_id,
            expected_bytes=len(b"verified disk"), expected_stream_sha256=digest,
        )
        self.assertEqual(received, result)

    def test_same_device_node_name_is_valid_on_different_hosts(self):
        header = CloneSessionHeader(
            session_id=self.header.session_id,
            source_identity=self.header.source_identity,
            receiver_identity=self.header.receiver_identity,
            source_device="/dev/sda",
            receiver_target_device="/dev/sda",
            source_size_bytes=self.header.source_size_bytes,
            logical_sector_size=self.header.logical_sector_size,
            chunk_size_bytes=self.header.chunk_size_bytes,
        )
        self.assertEqual(header.source_device, header.receiver_target_device)

    def test_rejects_non_normalized_device_paths(self):
        value = self.header.to_dict()
        value["receiver_target_device"] = "/dev/../dev/sdb"
        with self.assertRaisesRegex(RemoteCloneProtocolError, "normalized"):
            CloneSessionHeader.from_dict(value)

    def test_receiver_ready_frame_is_bound_to_session_and_target(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        ready = CloneSessionReady(self.header.session_id, self.header.receiver_target_device)
        send_session_ready(left, ready)
        received = receive_session_ready(
            right, session_id=self.header.session_id,
            expected_target_device=self.header.receiver_target_device,
        )
        self.assertEqual(received, ready)

    def test_receiver_ready_rejects_wrong_target(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_session_ready(
            left, CloneSessionReady(self.header.session_id, self.header.receiver_target_device),
        )
        with self.assertRaisesRegex(RemoteCloneProtocolError, "different session or target"):
            receive_session_ready(
                right, session_id=self.header.session_id,
                expected_target_device="/dev/other",
            )

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

    def test_rejects_destination_writer_overreporting(self):
        class BadWriter:
            def write(self, value):
                return len(value) + 1
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.sendall(b"bounded")
        with self.assertRaisesRegex(RemoteCloneProtocolError, "invalid byte count"):
            receive_disk_stream(
                right, BadWriter(), len(b"bounded"),
                session_id=self.header.session_id, chunk_size=64 * 1024,
            )

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

    def test_sender_reports_progress_in_bounded_chunks(self):
        payload = b"p" * (128 * 1024)
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        progress = []
        result = send_disk_stream(
            left, io.BytesIO(payload), len(payload),
            session_id=self.header.session_id, chunk_size=64 * 1024,
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(result.byte_count, len(payload))
        self.assertEqual(progress, [(64 * 1024, len(payload)), (len(payload), len(payload))])

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
