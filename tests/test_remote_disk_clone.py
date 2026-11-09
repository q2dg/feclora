import hashlib
import io
import json
import socket
import tempfile
import threading
import os
import unittest
from unittest.mock import patch

from feclora.network.remote_clone import (
    RemoteDiskCloneError,
    _readback_digest,
    build_remote_clone_header,
    receive_remote_disk,
    send_remote_disk,
)
from feclora.network.remote_clone_protocol import (
    CloneSessionHeader,
    CloneSessionReady,
    CloneVerificationResult,
    RemoteCloneCancelled,
    receive_disk_stream,
    receive_session_header,
    receive_session_ready,
    receive_verification_result,
    send_disk_stream,
    send_session_header,
    send_session_ready,
    send_verification_result,
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


class FakeSourceProcess:
    def __init__(self, payload):
        self.stdout = io.BytesIO(payload)
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
            receive_session_ready(
                sock, session_id=self.header.session_id,
                expected_target_device=self.header.receiver_target_device,
            )
            send_disk_stream(
                sock, io.BytesIO(self.payload), len(self.payload),
                session_id=self.header.session_id, chunk_size=65536,
            )
        thread = threading.Thread(target=send)
        thread.start()
        return thread

    def _receive(self, sock, *, geometry, process_factory, target_path="/dev/target", executables=None, safety_check=None, cancel_check=None):
        with tempfile.TemporaryDirectory() as directory:
            log_path = os.path.join(directory, "operations.jsonl")
            result = receive_remote_disk(
                TlsSocketProxy(sock),
                operation_log_path=log_path,
                local_identity="DNS:receiver.example",
                expected_peer_identity="DNS:source.example",
                target_path=target_path,
                confirmation="ERASE /dev/target FROM DNS:source.example",
                executables=executables or {"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                device_validator=lambda _path: True,
                runner=lambda *args, **kwargs: None,
                popen_factory=process_factory,
                safety_check=safety_check or (lambda _path: None),
                effective_uid=lambda: 0,
            )
            with open(log_path, encoding="utf-8") as journal:
                self.journal_events = [json.loads(line) for line in journal]
            return result

    def test_header_builder_uses_read_only_source_geometry(self):
        with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload), 512, True, "gpt")):
            header = build_remote_clone_header(
                "/dev/source", "/dev/target",
                source_identity="DNS:source.example",
                receiver_identity="DNS:receiver.example",
                executables={"lsblk": "/usr/bin/lsblk"},
            )
        self.assertEqual(header.source_size_bytes, len(self.payload))
        self.assertEqual(header.logical_sector_size, 512)
        self.assertEqual(header.source_device, "/dev/source")
        self.assertEqual(header.receiver_target_device, "/dev/target")
        self.assertEqual(len(header.session_id), 36)

    def test_header_builder_rejects_writable_source(self):
        with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload), 512, False, "gpt")):
            with self.assertRaisesRegex(RemoteDiskCloneError, "marked read-only"):
                build_remote_clone_header(
                    "/dev/source", "/dev/target",
                    source_identity="DNS:source.example",
                    receiver_identity="DNS:receiver.example",
                    executables={"lsblk": "/usr/bin/lsblk"},
                )

    def test_readback_reports_progress_and_checks_cancel(self):
        process = FakeSourceProcess(self.payload)
        progress = []
        digest = _readback_digest(
            "/dev/target", len(self.payload), "/usr/bin/dd",
            popen_factory=lambda *args, **kwargs: process,
            effective_uid=lambda: 0,
            progress_callback=lambda done, total: progress.append((done, total)),
        )
        self.assertEqual(digest, hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))

        cancelled = FakeSourceProcess(self.payload)
        with self.assertRaisesRegex(RemoteCloneCancelled, "cancelled destination read-back"):
            _readback_digest(
                "/dev/target", len(self.payload), "/usr/bin/dd",
                popen_factory=lambda *args, **kwargs: cancelled,
                effective_uid=lambda: 0,
                cancel_check=lambda: True,
            )

    def test_source_waits_for_receiver_readback_ack_and_journals_result(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        received = {}

        def receiver():
            header = receive_session_header(right)
            send_session_ready(
                right,
                CloneSessionReady(
                    session_id=header.session_id,
                    target_device=header.receiver_target_device,
                ),
            )
            destination = io.BytesIO()
            stream = receive_disk_stream(
                right, destination, header.source_size_bytes,
                session_id=header.session_id, chunk_size=header.chunk_size_bytes,
            )
            received["data"] = destination.getvalue()
            send_verification_result(
                right,
                CloneVerificationResult(
                    session_id=header.session_id, status="verified",
                    byte_count=header.source_size_bytes,
                    stream_sha256=stream.sha256, readback_sha256=stream.sha256,
                ),
            )

        worker = threading.Thread(target=receiver)
        worker.start()
        process = FakeSourceProcess(self.payload)
        with tempfile.TemporaryDirectory() as directory:
            with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload), 512, True, "gpt")):
                result = send_remote_disk(
                    TlsSocketProxy(left, peer="receiver.example"),
                    self.header,
                    operation_log_path=os.path.join(directory, "operations.jsonl"),
                    local_identity="DNS:source.example",
                    expected_peer_identity="DNS:receiver.example",
                    source_path="/dev/source",
                    confirmation="READ /dev/source TO DNS:receiver.example",
                    executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                    device_validator=lambda _path: True,
                    runner=lambda *args, **kwargs: None,
                    popen_factory=lambda *args, **kwargs: process,
                    safety_check=lambda _path: None,
                    effective_uid=lambda: 0,
                )
            with open(os.path.join(directory, "operations.jsonl"), encoding="utf-8") as journal:
                events = [json.loads(line) for line in journal]
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result.status, "verified")
        self.assertEqual(received["data"], self.payload)
        self.assertEqual([event["status"] for event in events], ["started", "completed"])

    def test_source_rejects_writable_source_before_streaming(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        with tempfile.TemporaryDirectory() as directory:
            with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload), 512, False, "gpt")):
                with self.assertRaisesRegex(RemoteDiskCloneError, "must be marked read-only"):
                    send_remote_disk(
                        TlsSocketProxy(left, peer="receiver.example"),
                        self.header,
                        operation_log_path=os.path.join(directory, "operations.jsonl"),
                        local_identity="DNS:source.example",
                        expected_peer_identity="DNS:receiver.example",
                        source_path="/dev/source",
                        confirmation="READ /dev/source TO DNS:receiver.example",
                        executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                        device_validator=lambda _path: True,
                        safety_check=lambda _path: None,
                        effective_uid=lambda: 0,
                        popen_factory=lambda *a, **k: self.fail("dd must not start"),
                    )

    def test_receiver_rejects_peer_selected_target_that_differs_from_local_choice(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_session_header(left, self.header)
        with self.assertRaisesRegex(RemoteDiskCloneError, "locally selected target"):
            self._receive(
                right, geometry=None, target_path="/dev/other",
                process_factory=lambda *a, **k: self.fail("dd must not start"),
            )

    def test_receiver_rejects_undersized_target_before_starting_writer(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        send_session_header(left, self.header)
        with patch("feclora.network.remote_clone._geometry", return_value=(len(self.payload) - 512, 512, False, "gpt")):
            with self.assertRaisesRegex(RemoteDiskCloneError, "smaller than the source"):
                self._receive(right, geometry=None, process_factory=lambda *a, **k: self.fail("dd must not start"))

    def test_receiver_accepts_larger_gpt_target_and_relocates_backup_header(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        source = self._start_source(left)
        digest = hashlib.sha256(self.payload).hexdigest()
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[0] == "/usr/bin/blkid":
                return type("Result", (), {"stdout": "gpt\n", "returncode": 0})()
            return type("Result", (), {"stdout": "", "returncode": 0})()

        with patch("feclora.network.remote_clone._geometry",
                   return_value=(len(self.payload) + 1024 * 1024, 512, False, "gpt")), \
             patch("feclora.network.remote_clone._readback_digest", return_value=digest), \
             patch("feclora.network.remote_clone.subprocess.run", side_effect=run):
            result = self._receive(
                right, geometry=None,
                process_factory=lambda *a, **k: FakeProcess(**k),
                executables={
                    "lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd",
                    "blkid": "/usr/bin/blkid", "sgdisk": "/usr/bin/sgdisk",
                },
            )
        source.join(timeout=5)
        self.assertFalse(source.is_alive())
        self.assertEqual(result.status, "verified")
        self.assertEqual(commands[0], ["/usr/bin/blkid", "-p", "-s", "PTTYPE", "-o", "value", "/dev/target"])
        self.assertEqual(commands[1][-2:], ["-e", "/dev/target"])
        self.assertEqual(commands[2][-2:], ["-v", "/dev/target"])

    def test_larger_gpt_target_is_rechecked_for_safety_before_relocation(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        source = self._start_source(left)
        digest = hashlib.sha256(self.payload).hexdigest()
        safety_checks = []
        commands = []

        def safety(path):
            safety_checks.append(path)
            if len(safety_checks) == 5:
                raise RuntimeError("copied target became mounted")

        def run(command, **kwargs):
            commands.append(command)
            return type("Result", (), {"stdout": "gpt\n", "returncode": 0})()

        with patch("feclora.network.remote_clone._geometry",
                   return_value=(len(self.payload) + 1024 * 1024, 512, False, "gpt")), \
             patch("feclora.network.remote_clone._readback_digest", return_value=digest), \
             patch("feclora.network.remote_clone.subprocess.run", side_effect=run):
            with self.assertRaisesRegex(RemoteDiskCloneError, "copied target became mounted"):
                self._receive(
                    right, geometry=None,
                    process_factory=lambda *a, **k: FakeProcess(**k),
                    safety_check=safety,
                    executables={
                        "lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd",
                        "blkid": "/usr/bin/blkid", "sgdisk": "/usr/bin/sgdisk",
                    },
                )
        source.join(timeout=5)
        self.assertFalse(source.is_alive())
        self.assertEqual(len(safety_checks), 5)
        self.assertEqual(commands[0][0], "/usr/bin/blkid")
        self.assertFalse(any(command[-2:] == ["-e", "/dev/target"] for command in commands))

    def test_larger_gpt_target_honors_cancellation_before_relocation(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        source = self._start_source(left)
        digest = hashlib.sha256(self.payload).hexdigest()
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            return type("Result", (), {"stdout": "gpt\\n", "returncode": 0})()

        with patch("feclora.network.remote_clone._geometry",
                   return_value=(len(self.payload) + 1024 * 1024, 512, False, "gpt")), \\
             patch("feclora.network.remote_clone._readback_digest", return_value=digest), \\
             patch("feclora.network.remote_clone.subprocess.run", side_effect=run):
            with self.assertRaisesRegex(RemoteDiskCloneError, "cancelled before GPT"):
                self._receive(
                    right, geometry=None,
                    process_factory=lambda *a, **k: FakeProcess(**k),
                    cancel_check=lambda: True,
                    executables={
                        "lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd",
                        "blkid": "/usr/bin/blkid", "sgdisk": "/usr/bin/sgdisk",
                    },
                )
        source.join(timeout=5)
        self.assertFalse(source.is_alive())
        self.assertEqual(commands[0][0], "/usr/bin/blkid")
        self.assertFalse(any(command[-2:] == ["-e", "/dev/target"] for command in commands))

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
                    target_path="/dev/target",
                    confirmation="yes",
                    executables={"lsblk": "/usr/bin/lsblk", "dd": "/usr/bin/dd"},
                    device_validator=lambda _path: True,
                    safety_check=lambda _path: None,
            )


if __name__ == "__main__":
    unittest.main()
