import json
import struct
import unittest

from feclora.deployment.local_control import (
    MAX_FRAME, LocalControlError, _receive, _send, local_control_request,
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

    def test_client_enforces_exact_arm_parameters_before_connecting(self):
        with self.assertRaisesRegex(LocalControlError, "exactly job_id"):
            local_control_request("/unused/socket", "arm", {"job_id": "not-enough"})

    def test_client_rejects_status_parameters_before_connecting(self):
        with self.assertRaisesRegex(LocalControlError, "does not accept"):
            local_control_request("/unused/socket", "status", {"unexpected": True})


if __name__ == "__main__":
    unittest.main()
