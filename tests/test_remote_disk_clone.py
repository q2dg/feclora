import hashlib
import io
import socket
import tempfile
import threading
import os
import unittest
from unittest.mock import patch

from feclora.network.remote_clone import (
    RemoteDiskCloneError,
    receive_remote_disk,
)
from feclora.network.remote_clone_protocol import (
    CloneSessionHeader,
    receive_verification_result,
    send_disk_stream,
    send_session_header,
)


class TlsSocketProxy:
    def __init__(self, sock, peer="source.example"):
        self.sock = sock
        self.peer = peer

    def sendall(self, data):
        return self.sock.sendall(data)

    def recv(self, count):
        return self.sock.recv(count)

    def getpeercert(self, binary_form=False):
        if binary_form:
            return b"test peer certificate"
        return {"subjectAltName": (("DNS", self.peer),)}


class Sink:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, value):
        self.data.extend(value)
        return len(value)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, **kwargs):
        self.stdin = Sink()
        self.returncode = 0
        self.terminated = False

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


class RemoteDiskReceiverTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"R" * 65536
        self.header = CloneSessionHeader(
            session_id="7a3c4c12-6a88-4f0d-bcc0-90df80a4adf1",
            source_identity="DNS:source.example",
            receiver_identity="DNS:receiver.example",
            source_device="/dev/source",
            receiver_target_device="/dev/target",
            source_size_bytes=len(self.payload),
            logical_sector_size=512,
            chunk_size_bytes=65536,
        )

    def _start_source(self, sock):
        def send():
            send_session_header(sock, self.header)
            send_disk_stream(
                sock, io.BytesIO(self.payload), len(self.payload),
                session_id=self.header.session_id, chunk_size=65536,
            )
        thread = threading.Thread(target=send)
        thread.start()
        return thread

    def _receive(self, sock, *, geometry, process_factory):
        with tempfile.TemporaryDirectory() as directory:
            log_path = os.path.join(directory, "operations.jsonl")
            result = receive_remote_disk(
                TlsSocketProxy(sock),
                operation_log_path=log_path,
                local_identity="DNS:receiver.example",
                expected_peer_identity="DNS:source.example",
                confirmation="ERASE /dev/target FROM DNS:source.example",
                executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                device_validator=lambda _path: True,
                runner=lambda *args, **kwargs: None,
                popen_factory=process_factory,
                safety_check=lambda _path: None,
                effective_uid=lambda: 0,
        )

    def test_receiver_rejects_undersized_target_before_starting_writer(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_session_header(left, self.header)
        with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload) - 512, 512, False, "gpt")):
            with self.assertRaisesRegex(RemoteDiskCloneError, "equal source and target"):
                self._receive(right, geometry=None, process_factory=lambda *a, **k: self.fail("dd must not start"))

    def test_receiver_writes_stream_and_requires_matching_readback(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        source = self._start_source(left)
        processes = []

        def factory(*args, **kwargs):
            process = FakeProcess(**kwargs)
            processes.append(process)
            return process

        digest = hashlib.sha256(self.payload).hexdigest()
        with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload), 512, False, "gpt")), patch(
            "feclora.network.remote_clone._readback_digest", return_value=digest
        ):
            result = self._receive(right, geometry=None, process_factory=factory)
        source.join(timeout=5)
        self.assertFalse(source.is_alive())
        self.assertEqual(result.status, "verified")
        self.assertEqual([event["status"] for event in self.journal_events], ["started", "completed"])
        self.assertEqual(processes[0].stdin.data, self.payload)
        self.assertTrue(processes[0].stdin.closed)
        acknowledgement = receive_verification_result(
            TlsSocketProxy(left, peer="receiver.example"),
            session_id=self.header.session_id,
            expected_bytes=len(self.payload),
            expected_stream_sha256=digest,
        )
        self.assertEqual(acknowledgement, result)

    def test_receiver_rejects_wrong_local_confirmation(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_session_header(left, self.header)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RemoteDiskCloneError, "explicit receiver authorization"):
                receive_remote_disk(
                    TlsSocketProxy(right),
                    operation_log_path=os.path.join(directory, "operations.jsonl"),
                    local_identity="DNS:receiver.example",
                    expected_peer_identity="DNS:source.example",
                    confirmation="yes",
                    executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                    device_validator=lambda _path: True,
                    safety_check=lambda _path: None,
            )


if __name__ == "__main__":
    unittest.main()
