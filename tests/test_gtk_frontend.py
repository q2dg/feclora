from __future__ import annotations

import ast
import unittest
from pathlib import Path


class GTKFrontendStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("src/feclora/gui_gtk.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.methods = {
            node.name: node
            for node in ast.walk(cls.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_frontend_fails_closed_to_native_wayland(self):
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', self.source)
        self.assertIn('os.environ.pop("DISPLAY", None)', self.source)
        self.assertIn('if not os.environ.get("WAYLAND_DISPLAY")', self.source)

    def test_overview_uses_real_status_api(self):
        method = ast.unparse(self.methods["_refresh_status"])
        self.assertIn('self.api.submit("status"', method)
        self.assertIn("_show_status", method)

    def test_inventory_uses_real_inventory_api_and_renders_nested_devices(self):
        method = ast.unparse(self.methods["_refresh_inventory"])
        self.assertIn('self.api.submit("inventory"', method)
        flatten = ast.unparse(self.methods["_flatten_devices"])
        self.assertIn('device.get("children")', flatten)
        render = ast.unparse(self.methods["_show_inventory"])
        for field in ("path", "type", "size_bytes", "model", "filesystem", "mountpoints"):
            self.assertIn(field, render)

    def test_disk_capture_uses_inventory_and_privileged_operation_api(self):
        populate = ast.unparse(self.methods["_populate_capture_devices"])
        start = ast.unparse(self.methods["_start_disk_capture"])
        poll = ast.unparse(self.methods["_poll_capture_status"])
        cancel = ast.unparse(self.methods["_cancel_disk_capture"])
        self.assertIn('self.api.submit("inventory"', self.source)
        self.assertIn('action = "capture_disk"', start)
        self.assertIn('action = "capture_partition"', start)
        self.assertIn('self.api.submit("local_operation_status"', poll)
        self.assertIn('self.api.submit("cancel_local_operation"', cancel)
        self.assertIn('d.get("type") == device_type', populate)
        self.assertIn("image_id", start)
        self.assertIn("image_format", start)
        self.assertIn("compression", start)
        self.assertIn("encrypt", start)

    def test_disk_capture_format_is_allowlisted_by_privileged_api(self):
        api_source = Path("src/feclora/api.py").read_text(encoding="utf-8")
        self.assertIn('"image_format", "encrypt_passphrase"', api_source)

    def test_disk_capture_polls_terminal_states_and_exposes_cancel(self):
        status = ast.unparse(self.methods["_show_capture_status"])
        self.assertIn('"completed"', status)
        self.assertIn('"failed"', status)
        self.assertIn('"cancelled"', status)
        self.assertIn('"interrupted"', status)
        self.assertIn("GLib.timeout_add_seconds", status)
        self.assertIn("Solicitar cancelación", self.source)
    def test_kiosk_window_is_fullscreen_and_not_decorated_or_closable(self):
        self.assertIn("self.window.fullscreen()", self.source)
        self.assertIn("self.window.set_decorated(False)", self.source)
        self.assertIn('self.window.connect("close-request"', self.source)


if __name__ == "__main__":
    unittest.main()
