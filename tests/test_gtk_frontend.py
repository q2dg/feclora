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
        method = ast.get_source_segment(self.source, self.methods["_refresh_status"])
        self.assertIn('self.api.submit("status"', method)
        self.assertIn("_show_status", method)

    def test_inventory_uses_real_inventory_api_and_renders_nested_devices(self):
        method = ast.get_source_segment(self.source, self.methods["_refresh_inventory"])
        self.assertIn('self.api.submit("inventory"', method)
        flatten = ast.get_source_segment(self.source, self.methods["_flatten_devices"])
        self.assertIn('device.get("children")', flatten)
        render = ast.get_source_segment(self.source, self.methods["_show_inventory"])
        for field in ("path", "type", "size_bytes", "model", "filesystem", "mountpoints"):
            self.assertIn(field, render)

    def test_disk_capture_uses_inventory_and_privileged_operation_api(self):
        populate = ast.get_source_segment(self.source, self.methods["_populate_capture_devices"])
        mode = ast.get_source_segment(self.source, self.methods["_capture_mode_changed"])
        start = ast.get_source_segment(self.source, self.methods["_start_disk_capture"])
        poll = ast.get_source_segment(self.source, self.methods["_poll_capture_status"])
        cancel = ast.get_source_segment(self.source, self.methods["_cancel_disk_capture"])
        self.assertIn('self.api.submit("inventory"', self.source)
        self.assertIn('action = "capture_disk"', start)
        self.assertIn('action = "capture_partition"', start)
        self.assertIn('self.api.submit("local_operation_status"', poll)
        self.assertIn('self.api.submit("cancel_local_operation"', cancel)
        self.assertIn('self._flatten_devices(inventory.get("devices"))', populate)
        self.assertIn('d.get("type") == device_type', mode)
        self.assertIn("image_id", start)
        self.assertIn("image_format", start)
        self.assertIn("compression", start)
        self.assertIn("encrypt", start)

    def test_lvm_and_stratis_capture_use_filtered_inventory_devices(self):
        mode = ast.get_source_segment(self.source, self.methods["_capture_mode_changed"])
        flatten = ast.get_source_segment(self.source, self.methods["_flatten_logical_volumes"])
        start = ast.get_source_segment(self.source, self.methods["_start_disk_capture"])
        self.assertIn('"capture_logical_volume"', start)
        self.assertIn('"capture_stratis_filesystem"', start)
        self.assertIn('d.get("type") == "dm"', mode)
        self.assertIn('"xfs"', mode)
        self.assertIn('group.get("status") == "healthy"', flatten)
        self.assertIn('volume.get("snapshot")', flatten)
        self.assertIn('identity_counts.get(identity) != 1', flatten)

    def test_btrfs_capture_uses_absolute_paths_and_incremental_parent(self):
        start = ast.get_source_segment(self.source, self.methods["_start_disk_capture"])
        mode = ast.get_source_segment(self.source, self.methods["_capture_mode_changed"])
        self.assertIn('"capture_btrfs_subvolume"', start)
        self.assertIn('"receive_btrfs_subvolume"', start)
        self.assertIn("source_path", start)
        self.assertIn("target_directory", start)
        self.assertIn("parent_path", start)
        self.assertIn("startswith(\"/\")", start)
        self.assertIn("kind == 4", mode)
        self.assertIn("kind == 5", mode)
        self.assertIn("Subvolúmenes Btrfs (ruta manual)", mode)

    def test_ddrescue_recovery_and_finalization_use_privileged_api(self):
        start = ast.get_source_segment(self.source, self.methods["_start_disk_capture"])
        mode = ast.get_source_segment(self.source, self.methods["_capture_mode_changed"])
        self.assertIn('self.api.submit("recover_disk"', start)
        self.assertIn('self.api.submit("finalize_recovery"', start)
        self.assertIn('"retry_passes"', start)
        self.assertIn('"resume"', start)
        self.assertIn("kind == 6", mode)
        self.assertIn("kind == 7", mode)

    def test_all_migrated_operations_are_exposed_by_api_dispatch(self):
        api_source = Path("src/feclora/api.py").read_text(encoding="utf-8")
        dispatch = api_source[api_source.index('    if action in {"capture_disk"'):]
        for action in ("capture_logical_volume", "capture_stratis_filesystem", "capture_btrfs_subvolume", "receive_btrfs_subvolume", "recover_disk", "finalize_recovery", "restore_disk", "restore_partition", "restore_logical_volume", "restore_stratis_filesystem", "clone_disk", "clone_partition", "build_recovery_iso", "build_deployment_bundle"):
            self.assertIn('"' + action + '"', dispatch)

    def test_disk_capture_format_is_allowlisted_by_privileged_api(self):
        api_source = Path("src/feclora/api.py").read_text(encoding="utf-8")
        self.assertIn('"image_format", "encrypt_passphrase"', api_source)

    def test_disk_capture_polls_terminal_states_and_exposes_cancel(self):
        status = ast.get_source_segment(self.source, self.methods["_show_capture_status"])
        self.assertIn('"completed"', status)
        self.assertIn('"failed"', status)
        self.assertIn('"cancelled"', status)
        self.assertIn('"interrupted"', status)
        self.assertIn("GLib.timeout_add_seconds", status)
        self.assertIn("Solicitar cancelación", self.source)
    def test_image_page_inspects_browses_downloads_and_extracts_partition_images(self):
        self.assertIn('self.api.submit("inspect_image_layout"', self.source)
        self.assertIn('self.api.submit("browse_image"', self.source)
        self.assertIn('self.api.submit("extract_partition_image"', self.source)
        self.assertIn("base64.b64decode(encoded, validate=True)", self.source)
        self.assertIn('destination.open("xb")', self.source)
        self.assertIn("self.image_layout", self.source)

    def test_proportional_restore_requires_smaller_target_and_kernel_identities(self):
        self.assertIn('"Restauración proporcional a disco menor"', self.source)
        self.assertIn('"restore_proportional_disk"', self.source)
        self.assertIn('source_device.get("major_minor")', self.source)
        self.assertIn('target_device.get("major_minor")', self.source)
        self.assertIn('target_device["size_bytes"] >= source_device["size_bytes"]', self.source)

    def test_restore_and_clone_operations_use_inventory_images_and_exact_confirmation(self):
        self.assertIn('self.api.submit("images"', self.source)
        self.assertIn('"restore_disk"', self.source)
        self.assertIn('"restore_partition"', self.source)
        self.assertIn('"restore_logical_volume"', self.source)
        self.assertIn('"restore_stratis_filesystem"', self.source)
        self.assertIn('"clone_disk"', self.source)
        self.assertIn('"clone_partition"', self.source)
        self.assertIn('"build_recovery_iso"', self.source)
        self.assertIn('"build_deployment_bundle"', self.source)
        self.assertIn('target_wwn and not target_serial', self.source)
        self.assertIn('base_iso.lower().endswith(".iso")', self.source)
        self.assertIn('self.api.submit("remote_repositories"', self.source)
        self.assertIn('self.api.submit("repository_images"', self.source)
        self.assertIn('self.capture_repository.connect("notify::selected"', self.source)
        self.assertIn("self.capture_source_label.set_visible(source_visible)", self.source)
        self.assertIn('params["repository_id"] = selected_repository["id"]', self.source)
        self.assertIn('repository.get("mounted")', self.source)
        self.assertIn('repository.get("verified")', self.source)
        self.assertIn('json.loads(job_text)', self.source)
        self.assertIn("capture_bundle_name_label.set_visible(is_bundle)", self.source)
        self.assertIn("capture_deployment_job_label.set_visible(is_bundle)", self.source)
        self.assertIn('confirmation != expected', self.source)
        self.assertIn('image.get("image_type") != expected_type', self.source)

    def test_kiosk_window_is_fullscreen_and_not_decorated_or_closable(self):
        self.assertIn("self.window.fullscreen()", self.source)
        self.assertIn("self.window.set_decorated(False)", self.source)
        self.assertIn('self.window.connect("close-request"', self.source)


if __name__ == "__main__":
    unittest.main()
