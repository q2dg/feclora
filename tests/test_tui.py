import unittest
import importlib.util
from unittest.mock import AsyncMock, patch

if importlib.util.find_spec("textual") is None:
    DataTable = None
    Static = None
    FecloraTUI = None
else:
    from textual.widgets import DataTable, Input, Select, Static
    from feclora.tui import FecloraTUI


@unittest.skipIf(FecloraTUI is None, "Textual is not installed")
class FecloraTUITests(unittest.IsolatedAsyncioTestCase):
    async def test_keyboard_navigation_opens_inventory_and_renders_nested_devices(self):
        async def api(action, params=None, on_event=None):
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "inventory":
                return {
                    "devices": [{
                        "path": "/dev/sda",
                        "type": "disk",
                        "size_bytes": 1024,
                        "children": [{
                            "path": "/dev/sda1",
                            "type": "part",
                            "size_bytes": 512,
                            "mountpoints": ["/"],
                        }],
                    }]
                }
            if action == "images":
                return {"images": []}
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                self.assertTrue(app.query_one("#first-run").display)
                await pilot.click("#continue")
                await pilot.pause()
                await pilot.click("#nav-inventory")
                await pilot.pause()
                self.assertIn("Inventario", str(app.query_one("#page-title", Static).render()))
                self.assertTrue(app.query_one("#inventory-table", DataTable).display)
                self.assertEqual(app.query_one("#inventory-table", DataTable).row_count, 2)
                await pilot.click("#nav-operations")
                await pilot.pause()
                self.assertTrue(app.query_one("#operations-form").display)
                self.assertEqual(app.query_one("#operation-type").value, "capture_disk")

    async def test_disk_capture_uses_allowlisted_api_and_reports_completion(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "inventory":
                return {"devices": [{"path": "/dev/sda", "type": "disk", "size_bytes": 1024}]}
            if action == "images":
                return {"images": []}
            if action == "capture_disk":
                return {"operation_id": "op-test", "status": "running"}
            if action == "local_operation_status":
                return {"operation_id": "op-test", "state": "completed", "progress": 100}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.click("#continue")
                await pilot.click("#nav-operations")
                await pilot.pause()
                app.query_one("#source-device", Select).value = "/dev/sda"
                app.query_one("#new-image-id", Input).value = "test-image"
                await pilot.click("#operation-start")
                await pilot.pause()
                self.assertIn(("capture_disk", {
                    "source": "/dev/sda",
                    "image_id": "test-image",
                    "compression": "zstd",
                    "encrypt": False,
                    "image_format": "raw",
                }), requests)
                self.assertIn("completada", str(app.query_one("#operation-result", Static).render()).lower())

    async def test_image_verification_uses_selected_image_id(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "images":
                return {"images": [{"image_id": "image-test", "image_type": "disk", "source_size_bytes": 2048}]}
            if action == "verify_image":
                return {"valid": True}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.click("#continue")
                await pilot.click("#nav-images")
                await pilot.pause()
                app.query_one("#page-table", DataTable).focus()
                await pilot.press("enter")
                await pilot.click("#page-action")
                self.assertIn(("verify_image", {"image_id": "image-test"}), requests)


if __name__ == "__main__":
    unittest.main()
