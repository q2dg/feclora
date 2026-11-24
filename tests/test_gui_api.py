from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from feclora.gui_api import TkAPIClient


class FakeRoot:
    def __init__(self):
        self.callbacks = {}
        self.next_id = 0
        self.cancelled = []

    def after(self, delay, callback):
        self.next_id += 1
        self.callbacks[self.next_id] = callback
        return self.next_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)
        self.callbacks.pop(callback_id, None)

    def fire(self):
        callback_id = min(self.callbacks)
        callback = self.callbacks.pop(callback_id)
        callback()


class TkAPIClientTests(unittest.TestCase):
    def test_callbacks_are_dispatched_by_tk_poll_on_main_thread(self):
        root = FakeRoot()
        client = TkAPIClient(root, poll_interval_ms=5)
        main_thread = threading.get_ident()
        delivered = []

        async def fake_call(action, params, on_event=None):
            self.assertEqual(action, "inventory")
            self.assertEqual(params, {"scope": "all"})
            on_event({"event": "progress", "percent": 50})
            return {"devices": []}

        try:
            with patch("feclora.gui_api.call_feclora", new=fake_call):
                future = client.submit(
                    "inventory",
                    {"scope": "all"},
                    on_event=lambda event: delivered.append(("event", event, threading.get_ident())),
                    on_success=lambda result: delivered.append(("success", result, threading.get_ident())),
                )
                self.assertEqual(future.result(timeout=2), {"devices": []})

            self.assertEqual(delivered, [])
            root.fire()
            self.assertEqual([item[0] for item in delivered], ["event", "success"])
            self.assertTrue(all(item[2] == main_thread for item in delivered))
        finally:
            client.close()

    def test_closed_client_rejects_new_requests(self):
        client = TkAPIClient(FakeRoot())
        client.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            client.submit("inventory")


if __name__ == "__main__":
    unittest.main()
