import json
import os
import stat
import struct
import threading
import unittest
from unittest import mock

from feclora.deployment.local_control import (
    MAX_FRAME, LocalControlError, LocalControlServer, _receive, _send, local_control_request,
)


class FakeSocket:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.outgoing = bytearray()

    def recv(self, count):
        data = bytes(self.incoming[:count])
        del self.incoming[:count]
        return data

    def sendall(self, data):
        self.outgoing.extend(data)


def frame(value):
    data = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(data)) + data


class LocalControlProtocolTests(unittest.TestCase):
    def test_status_request_round_trip(self):
        sock = FakeSocket(frame({"action": "status", "params": {}}))
        self.assertEqual(_receive(sock), {"action": "status", "params": {}})
        _send(sock, {"ok": True, "data": {"job_state": "created"}})
        size = struct.unpack("!I", sock.outgoing[:4])[0]
        self.assertEqual(json.loads(sock.outgoing[4:4 + size]), {
            "ok": True, "data": {"job_state": "created"},
        })

    def test_rejects_unknown_action(self):
        with self.assertRaisesRegex(LocalControlError, "unsupported"):
            _receive(FakeSocket(frame({"action": "exec", "params": {"command": "id"}})))

    def test_rejects_unhashable_action(self):
        with self.assertRaisesRegex(LocalControlError, "unsupported"):
            _receive(FakeSocket(frame({"action": [], "params": {}})))

    def test_rejects_extra_request_fields(self):
        with self.assertRaisesRegex(LocalControlError, "exactly"):
            _receive(FakeSocket(frame({"action": "status", "params": {}, "uid": 0})))

    def test_arm_requires_job_and_confirmation(self):
        with self.assertRaisesRegex(LocalControlError, "exactly job_id"):
            _receive(FakeSocket(frame({"action": "arm", "params": {"job_id": "abc"}})))

    def test_status_rejects_parameters(self):
        with self.assertRaisesRegex(LocalControlError, "does not accept"):
            _receive(FakeSocket(frame({"action": "status", "params": {"anything": True}})))

    def test_rejects_duplicate_fields(self):
        payload = b'{"action":"status","action":"cancel","params":{}}'
        with self.assertRaisesRegex(LocalControlError, "duplicate"):
            _receive(FakeSocket(struct.pack("!I", len(payload)) + payload))

    def test_rejects_oversized_frame(self):
        sock = FakeSocket(struct.pack("!I", MAX_FRAME + 1))
        with self.assertRaisesRegex(LocalControlError, "frame length"):
            _receive(sock)

    def test_client_rejects_non_string_action_before_connecting(self):
        with self.assertRaisesRegex(LocalControlError, "unsupported"):
            local_control_request("/unused/socket", [], {})

    def test_client_rejects_falsey_non_dict_parameters_before_connecting(self):
        with self.assertRaisesRegex(LocalControlError, "unsupported"):
            local_control_request("/unused/socket", "status", [])

    def test_client_enforces_exact_arm_parameters_before_connecting(self):
        with self.assertRaisesRegex(LocalControlError, "exactly job_id"):
            local_control_request("/unused/socket", "arm", {"job_id": "not-enough"})

    def test_listener_thread_start_failure_closes_socket_and_resets_state(self):
        server = LocalControlServer("/run/feclora/test.sock", lambda *_args: {})
        listener = mock.Mock()
        info = mock.Mock(st_mode=stat.S_IFSOCK | 0o600, st_dev=1, st_ino=2)
        parent_info = mock.Mock(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        class BrokenThread:
            def __init__(self, **_kwargs):
                pass
            def start(self):
                raise RuntimeError("thread start failed")
        with mock.patch("feclora.deployment.local_control.os.lstat", side_effect=[
            parent_info, FileNotFoundError, info, info,
        ]), mock.patch("feclora.deployment.local_control.socket.socket", return_value=listener), \
             mock.patch("feclora.deployment.local_control.os.chmod"), \
             mock.patch("feclora.deployment.local_control.os.unlink") as unlink, \
             mock.patch("feclora.deployment.local_control.threading.Thread", BrokenThread):
            listener.getsockopt.return_value = 0
            with mock.patch.object(listener, "bind"), mock.patch.object(listener, "listen"), \
                 mock.patch.object(listener, "settimeout"):
                with self.assertRaisesRegex(RuntimeError, "thread start failed"):
                    server.start()
        listener.close.assert_called_once()
        unlink.assert_called_once_with(server.path)
        self.assertIsNone(server._listener)
        self.assertIsNone(server._thread)
        self.assertIsNone(server._socket_identity)

    def test_stop_retains_listener_thread_and_socket_after_join_timeout(self):
        server = LocalControlServer("/run/feclora/test.sock", lambda *_args: {})
        server._listener = mock.Mock()
        server._thread = mock.Mock()
        server._thread.is_alive.return_value = True
        server._socket_identity = (1, 2)
        with mock.patch("feclora.deployment.local_control.os.lstat") as lstat, \
             mock.patch("feclora.deployment.local_control.os.unlink") as unlink:
            with self.assertRaisesRegex(LocalControlError, "did not stop"):
                server.stop()
        self.assertIsNotNone(server._thread)
        self.assertEqual(server._socket_identity, (1, 2))
        lstat.assert_not_called()
        unlink.assert_not_called()

    def test_stop_retains_listener_when_close_fails_for_retry(self):
        server = LocalControlServer("/run/feclora/test.sock", lambda *_args: {})
        listener = mock.Mock()
        listener.close.side_effect = OSError("close failed")
        server._listener = listener
        server._thread = mock.Mock()
        server._thread.is_alive.return_value = False
        server._socket_identity = (1, 2)
        socket_info = mock.Mock(
            st_mode=stat.S_IFSOCK | 0o600, st_uid=os.geteuid(), st_dev=1, st_ino=2,
        )
        with mock.patch("feclora.deployment.local_control.os.lstat", return_value=socket_info) as lstat, \
             mock.patch("feclora.deployment.local_control.os.unlink") as unlink:
            with self.assertRaisesRegex(LocalControlError, "cannot close"):
                server.stop()
            self.assertIs(server._listener, listener)
            self.assertIsNone(server._thread)
            self.assertEqual(server._socket_identity, (1, 2))
            lstat.assert_not_called()
            unlink.assert_not_called()
            listener.close.side_effect = None
            server.stop()
        self.assertIsNone(server._listener)
        self.assertIsNone(server._socket_identity)
        unlink.assert_called_once_with(server.path)

    def test_client_rejects_status_parameters_before_connecting(self):
        with self.assertRaisesRegex(LocalControlError, "does not accept"):
            local_control_request("/unused/socket", "status", {"unexpected": True})


if __name__ == "__main__":
    unittest.main()
