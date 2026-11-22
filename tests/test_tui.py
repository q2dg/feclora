import unittest
import importlib.util
from unittest.mock import AsyncMock, patch

if importlib.util.find_spec("textual") is None:
    DataTable = None
    Static = None
    FecloraTUI = None
else:
    from textual.widgets import DataTable, Static
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
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)):
            app = FecloraTUI()
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#nav-inventory")
                await pilot.pause()
                self.assertIn("Inventario", str(app.query_one("#page-title", Static).render()))
                self.assertTrue(app.query_one("#inventory-table", DataTable).display)
                self.assertEqual(app.query_one("#inventory-table", DataTable).row_count, 2)


if __name__ == "__main__":
    unittest.main()
