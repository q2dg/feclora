import asyncio
import json
import subprocess
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

from feclora.tui_api import TUIAPIError, _request_bytes, call_feclora

ROOT = Path(__file__).resolve().parents[1]


class _Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True


class _Reader:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    async def readline(self):
        return self.chunks.pop(0) if self.chunks else b""

    async def read(self, size):
        return b""


class _Process:
    def __init__(self, stdout, returncode=0, stderr=b""):
        self.stdin = _Writer()
        self.stdout = _Reader(stdout)
        self.stderr = _Reader([stderr])
        self.returncode = returncode
        self.terminated = False

    async def wait(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


class TUIAPITests(unittest.TestCase):
    def test_root_helper_rejects_unknown_actions_and_extra_arguments(self):
        helper = ROOT / "src/feclora/data/feclora-api"
        for arguments in (["unsupported"], ["status", "extra"]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    ["/bin/sh", str(helper), *arguments],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(result.returncode, 2)
                expected = "one API command" if len(arguments) > 1 else "unsupported action"
                self.assertIn(expected, result.stderr)

    def test_request_is_bounded_json_for_one_action(self):
        request = json.loads(_request_bytes("inventory", {}).decode("utf-8"))
        self.assertEqual(request, {"action": "inventory", "params": {}})
        with self.assertRaisesRegex(TUIAPIError, "invalid"):
            _request_bytes("../status", {})
        with self.assertRaisesRegex(TUIAPIError, "size limit"):
            _request_bytes("status", {"value": "x" * (128 * 1024)})

    def test_call_streams_events_and_returns_the_final_result(self):
        response = [
            b'{"event":"progress","bytes_done":512}\n',
            b'{"ok":true,"data":{"devices":[]}}\n',
        ]
        process = _Process(response)
        events = []
        with patch(
            "feclora.tui_api.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as spawn:
            result = asyncio.run(call_feclora("inventory", on_event=events.append))
        self.assertEqual(result, {"devices": []})
        self.assertEqual(events, [{"event": "progress", "bytes_done": 512}])
        self.assertEqual(
            spawn.call_args.args,
            ("/usr/bin/sudo", "-n", "/usr/libexec/feclora/feclora-api", "inventory"),
        )
        self.assertTrue(process.stdin.closed)
        self.assertIn(b'"action":"inventory"', process.stdin.data)

    def test_api_error_is_reported_without_a_success_fallback(self):
        process = _Process(
            [b'{"ok":false,"error":"inventory unavailable"}\n'],
            returncode=1,
        )
        with patch(
            "feclora.tui_api.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            with self.assertRaisesRegex(TUIAPIError, "inventory unavailable"):
                asyncio.run(call_feclora("inventory"))


if __name__ == "__main__":
    unittest.main()
