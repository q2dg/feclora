import asyncio
import unittest
import importlib.util
from unittest.mock import AsyncMock, patch

if importlib.util.find_spec("textual") is None:
    DataTable = None
    Static = None
    FecloraTUI = None
else:
    from textual.widgets import Button, DataTable, Input, Select, Static
    from feclora.tui import FecloraTUI


@unittest.skipIf(FecloraTUI is None, "Textual is not installed")
class FecloraTUITests(unittest.IsolatedAsyncioTestCase):
    async def test_classic_dos_theme_is_registered_and_selected(self):
        async def api(action, params=None, on_event=None):
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(80, 25)):
                self.assertEqual(app.theme, "feclora-classic")

    async def test_initial_screen_renders_while_keyboard_query_is_pending(self):
        query_started = asyncio.Event()
        finish_query = asyncio.Event()

        async def api(action, params=None, on_event=None):
            if action == "get_keyboard_layout":
                query_started.set()
                await finish_query.wait()
                return {"layout": "us"}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(80, 25)) as pilot:
                await asyncio.wait_for(query_started.wait(), timeout=2)
                await pilot.pause()
                self.assertTrue(app.query_one("#first-run").display)
                self.assertGreater(app.query_one("#first-title").region.height, 0)
                finish_query.set()

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
            if action == "remote_repositories":
                return {"repositories": []}
            if action == "s3_repositories":
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
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
            if action == "remote_repositories":
                return {"repositories": []}
            if action == "s3_repositories":
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
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

    async def test_btrfs_send_capture_and_receive_use_explicit_paths(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action in {"remote_repositories", "s3_repositories"}:
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "inventory":
                return {"devices": []}
            if action == "images":
                return {"images": []}
            if action in {"capture_btrfs_subvolume", "receive_btrfs_subvolume"}:
                return {"operation_id": "btrfs-op", "status": "running"}
            if action == "local_operation_status":
                return {"operation_id": "btrfs-op", "state": "completed", "events": []}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.click("#continue")
                await pilot.click("#nav-operations")
                await pilot.pause()
                app.query_one("#operation-type", Select).value = "capture_btrfs_subvolume"
                await app._update_operation_fields()
                app.query_one("#new-image-id", Input).value = "root-stream"
                app.query_one("#btrfs-source-path", Input).value = "/mnt/btrfs/root"
                app.query_one("#btrfs-capture-parent", Input).value = "/mnt/btrfs/base"
                await app.run_operation()
                self.assertIn(("capture_btrfs_subvolume", {
                    "source_path": "/mnt/btrfs/root", "image_id": "root-stream",
                    "parent_path": "/mnt/btrfs/base",
                    "compression": "zstd", "encrypt": False,
                }), requests)
                app.query_one("#operation-type", Select).value = "receive_btrfs_subvolume"
                await app._update_operation_fields()
                app.query_one("#new-image-id", Input).value = "root-stream"
                app.query_one("#btrfs-target-directory", Input).value = "/mnt/btrfs/received"
                app.query_one("#btrfs-receive-parent", Input).value = "/mnt/btrfs/received/base"
                self.assertTrue(app.query_one("#new-image-label", Static).display)
                await app.run_operation()
                self.assertIn(("receive_btrfs_subvolume", {
                    "image_id": "root-stream",
                    "target_directory": "/mnt/btrfs/received",
                    "parent_path": "/mnt/btrfs/received/base",
                }), requests)

    async def test_image_verification_uses_selected_image_id(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action == "remote_repositories":
                return {"repositories": []}
            if action == "s3_repositories":
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
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
                await app.load_page("images")
                table = app.query_one("#page-table", DataTable)
                for _ in range(50):
                    await pilot.pause(0.1)
                    if table.row_count:
                        break
                self.assertGreater(table.row_count, 0)
                table.focus()
                table.action_select_cursor()
                action_button = app.query_one("#page-action", Button)
                for _ in range(50):
                    await pilot.pause(0.1)
                    if action_button.display:
                        break
                self.assertTrue(action_button.display)
                await pilot.click("#page-action")
                self.assertIn(("verify_image", {"image_id": "image-test"}), requests)

    async def test_symmetric_capture_passphrase_is_sent_only_to_one_shot_channel(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action in {"remote_repositories", "s3_repositories"}:
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "inventory":
                return {"devices": [{"path": "/dev/sda", "type": "disk", "size_bytes": 2048}]}
            if action == "images":
                return {"images": []}
            if action == "capture_disk":
                return {"operation_id": "op-secret", "status": "running"}
            if action == "provide_capture_passphrase":
                return {"accepted": True}
            if action == "local_operation_status":
                return {"operation_id": "op-secret", "state": "completed", "events": []}
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
                app.query_one("#new-image-id", Input).value = "secret-image"
                app.query_one("#encrypt-passphrase-toggle").variant = "success"
                app.query_one("#capture-passphrase", Input).value = "correct horse battery"
                await pilot.click("#operation-start")
                capture = next(params for action, params in requests if action == "capture_disk")
                self.assertNotIn("age_passphrase", capture)
                self.assertTrue(capture["encrypt_passphrase"])
                self.assertIn(("provide_capture_passphrase", {
                    "operation_id": "op-secret",
                    "passphrase": "correct horse battery",
                }), requests)
                self.assertEqual(app.query_one("#capture-passphrase", Input).value, "")

    async def test_operation_history_requires_exact_confirmation_to_cancel(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action in {"remote_repositories", "s3_repositories"}:
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "local_operations":
                return {"operations": [{
                    "operation_id": "operation-test",
                    "action": "restore_disk",
                    "state": "running",
                    "events": [{
                        "timestamp": "2025-01-01T00:00:00Z",
                        "state": "running",
                        "details": {},
                    }],
                }]}
            if action == "cancel_local_operation":
                return {"operation_id": params["operation_id"], "state": "running", "requested": True}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.click("#continue")
                await pilot.click("#nav-operation-log")
                await pilot.pause()
                await pilot.pause()
                table = app.query_one("#page-table", DataTable)
                for _ in range(50):
                    await pilot.pause(0.1)
                    if table.row_count:
                        break
                self.assertGreater(table.row_count, 0)
                table.focus()
                table.move_cursor(row=0)
                table.action_select_cursor()
                await pilot.pause()
                await pilot.pause()
                action_button = app.query_one("#page-action", Button)
                for _ in range(50):
                    await pilot.pause(0.1)
                    if not action_button.disabled:
                        break
                self.assertFalse(action_button.disabled)
                await pilot.click("#page-action")
                self.assertNotIn(("cancel_local_operation", {"operation_id": "operation-test"}), requests)

                app.query_one("#page-confirmation", Input).value = "CANCEL operation-test"
                await pilot.click("#page-action")
                self.assertIn(("cancel_local_operation", {"operation_id": "operation-test"}), requests)

    async def test_pxe_services_require_a_successful_profile_preflight(self):
        requests = []

        async def api(action, params=None, on_event=None):
            requests.append((action, params))
            if action == "get_keyboard_layout":
                return {"layout": "us"}
            if action in {"remote_repositories", "s3_repositories"}:
                return {"repositories": []}
            if action == "systemd_credentials":
                return {"credentials": []}
            if action == "status":
                return {"hostname": "feclora-test", "platform": "Fedora", "services": {}}
            if action == "pxe_service_status":
                return {"active": False, "configured": False}
            if action == "network_interfaces":
                return {"interfaces": [{
                    "binding": "eth0:192.0.2.10",
                    "interface": "eth0",
                    "address": "192.0.2.10",
                    "prefix_length": 24,
                }]}
            if action == "pxe_age_passphrase_status":
                return {"available": False, "waiting": False, "submitted": False}
            if action == "validate_pxe_profile":
                return {"valid": True, "message": "PXE profile validated."}
            if action == "start_pxe_services":
                return {"active": True, "message": "PXE started."}
            raise AssertionError(f"unexpected API action: {action}")

        with patch("feclora.tui.call_feclora", new=AsyncMock(side_effect=api)), \
                patch.object(FecloraTUI, "_save_language"):
            app = FecloraTUI()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                await pilot.click("#continue")
                await pilot.click("#nav-server")
                await app.load_system_page("server")
                server_interface = app.query_one("#server-interface", Select)
                for _ in range(50):
                    if any(option[1] == "eth0:192.0.2.10" for option in server_interface._options):
                        break
                    await pilot.pause(0.1)
                self.assertTrue(
                    any(option[1] == "eth0:192.0.2.10" for option in server_interface._options),
                    "server interface options were not loaded",
                )
                server_interface.value = "eth0:192.0.2.10"
                await app.validate_pxe_profile()
                self.assertIn(("validate_pxe_profile", {
                    "interface": "eth0",
                    "address": "192.0.2.10",
                    "prefix_length": 24,
                    "mode": "proxy",
                    "pool_start": None,
                    "pool_end": None,
                    "lease_time": "1h",
                    "gateway": None,
                    "dns_server": None,
                    "http_port": 8080,
                    "authoritative_confirmed": False,
                    "max_clients": None,
                    "max_duration_seconds": None,
                }), requests)
                self.assertFalse(app.query_one("#pxe-start", Button).disabled)
                await app.start_pxe_services()
                self.assertIn(("start_pxe_services", next(
                    params for action, params in requests if action == "validate_pxe_profile"
                )), requests)


if __name__ == "__main__":
    unittest.main()
