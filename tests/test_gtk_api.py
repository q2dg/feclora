from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from feclora.gtk_api import GtkAPIClient


class GtkAPIClientTests(unittest.TestCase):
    def test_callbacks_are_dispatched_on_main_loop(self):
        pending = []
        main_thread = threading.get_ident()
        delivered = []

        async def fake_call(action, params, on_event=None):
            self.assertEqual(action, "inventory")
            self.assertEqual(params, {"scope": "all"})
            on_event({"event": "progress", "percent": 50})
            return {"devices": []}

        client = GtkAPIClient(dispatch=lambda callback: pending.append(callback))
        try:
            with patch("feclora.gtk_api.call_feclora", new=fake_call):
                future = client.submit(
                    "inventory", {"scope": "all"},
                    on_event=lambda event: delivered.append(("event", event, threading.get_ident())),
                    on_success=lambda result: delivered.append(("success", result, threading.get_ident())),
                )
                self.assertEqual(future.result(timeout=2), {"devices": []})
            self.assertEqual(delivered, [])
            for callback in pending:
                callback()
            self.assertEqual([item[0] for item in delivered], ["event", "success"])
            self.assertTrue(all(item[2] == main_thread for item in delivered))
        finally:
            client.close()

    def test_worker_errors_are_dispatched_and_preserved_on_future(self):
        pending = []
        delivered = []
        failure = RuntimeError("API unavailable")

        async def fake_call(action, params, on_event=None):
            raise failure

        client = GtkAPIClient(dispatch=lambda callback: pending.append(callback))
        try:
            with patch("feclora.gtk_api.call_feclora", new=fake_call):
                future = client.submit("inventory", on_error=delivered.append)
                with self.assertRaisesRegex(RuntimeError, "API unavailable"):
                    future.result(timeout=2)
            self.assertEqual(delivered, [])
            self.assertEqual(len(pending), 1)
            pending.pop()()
            self.assertEqual(delivered, [failure])
        finally:
            client.close()

    def test_close_suppresses_callbacks_already_queued_for_dispatch(self):
        pending = []
        delivered = []

        async def fake_call(action, params, on_event=None):
            return {"ok": True}

        client = GtkAPIClient(dispatch=lambda callback: pending.append(callback))
        with patch("feclora.gtk_api.call_feclora", new=fake_call):
            future = client.submit("inventory", on_success=delivered.append)
            self.assertEqual(future.result(timeout=2), {"ok": True})
        self.assertEqual(len(pending), 1)
        client.close()
        pending.pop()()
        self.assertEqual(delivered, [])

    def test_closed_client_rejects_new_requests(self):
        client = GtkAPIClient(dispatch=lambda callback: None)
        client.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            client.submit("inventory")


if __name__ == "__main__":
    unittest.main()
