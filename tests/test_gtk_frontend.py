from __future__ import annotations

import ast
import re
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

    def test_frontend_uses_libadwaita_application_shell(self):
        self.assertIn('gi.require_version("Adw", "1")', self.source)
        self.assertIn("Adw.ApplicationWindow(application=application)", self.source)
        self.assertIn("Adw.ToolbarView()", self.source)
        self.assertIn("Adw.HeaderBar()", self.source)
        self.assertIn("Adw.WindowTitle(title, subtitle)", self.source)
        self.assertIn("Adw.Clamp()", self.source)
        self.assertIn("Adw.ToastOverlay()", self.source)
        self.assertIn("Adw.Toast.new(message)", self.source)
        self.assertIn('app = Adw.Application(application_id="org.feclora.Appliance")', self.source)
        self.assertNotIn("Gtk.ApplicationWindow(application=application)", self.source)

    def test_navigation_uses_adaptive_libadwaita_split_view(self):
        self.assertIn("Adw.NavigationSplitView()", self.source)
        self.assertIn("Adw.NavigationPage.new(sidebar_scroller, \"Feclora\")", self.source)
        self.assertIn("Adw.NavigationPage.new(content, self.tr(\"overview\"))", self.source)
        self.assertIn("self.navigation_split.set_min_sidebar_width(220)", self.source)
        self.assertIn("self.navigation_split.set_sidebar_width_fraction(0.25)", self.source)
        self.assertIn('self.navigation_split.connect("notify::collapsed"', self.source)
        self.assertIn("self.navigation_split.set_show_content(True)", self.source)
        self.assertIn("self.navigation_split.set_show_content(False)", self.source)
        self.assertIn("self.window_title.set_title(page_title)", self.source)

    def test_navigation_sidebar_uses_activatable_libadwaita_rows(self):
        method = ast.get_source_segment(self.source, self.methods["_show_navigation"])
        self.assertIn('Adw.PreferencesGroup(title="Secciones")', method)
        self.assertIn("Adw.ActionRow(title=self.tr(PAGE_MESSAGE_KEYS[page_id]))", method)
        self.assertIn('row.connect("activated", self._select_page, page_id)', method)
        self.assertIn("row.set_activatable(True)", method)
        self.assertIn("self.navigation_rows[page_id] = row", method)
        self.assertNotIn("Gtk.Button(label=self.tr(PAGE_MESSAGE_KEYS[page_id]))", method)

    def test_navigation_marks_the_current_page_in_sidebar(self):
        show = ast.get_source_segment(self.source, self.methods["_show_navigation"])
        select = ast.get_source_segment(self.source, self.methods["_select_page"])
        self.assertIn("self.navigation_icons: dict[str, Gtk.Image] = {}", show)
        self.assertIn("self.navigation_icons[page_id] = icon", show)
        self.assertIn('row.set_subtitle("Página actual" if selected else "")', select)
        self.assertIn('icon.set_from_icon_name("emblem-ok-symbolic" if selected else "go-next-symbolic")', select)
        self.assertIn("for navigation_id, row in self.navigation_rows.items()", select)

    def test_frontend_fails_closed_to_native_wayland(self):
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', self.source)
        self.assertIn('os.environ.pop("DISPLAY", None)', self.source)
        self.assertIn('if not os.environ.get("WAYLAND_DISPLAY")', self.source)

    def test_wayland_environment_is_set_before_gtk_import(self):
        gtk_import = self.source.index("import gi")
        self.assertLess(self.source.index('os.environ["GDK_BACKEND"] = "wayland"'), gtk_import)
        self.assertLess(self.source.index('os.environ.pop("DISPLAY", None)'), gtk_import)

    def test_validator_checks_all_contracts_before_reporting_success(self):
        validator = Path("build/validate.sh").read_text(encoding="utf-8")
        final_guard = validator.rfind("if (( ERRORS > 0 )); then")
        last_contract = validator.rfind("require_text ")
        self.assertEqual(validator.count("if (( ERRORS > 0 )); then"), 1)
        self.assertGreater(final_guard, last_contract)
        self.assertIn("weston(-libs)?|gtk4|libadwaita", validator)
        self.assertIn("xorg-x11-server-Xwayland", validator)

    def test_gtk_retains_every_literal_privileged_action_from_textual(self):
        tui_source = Path("src/feclora/tui.py").read_text(encoding="utf-8")
        tui_actions = set(re.findall(r"""call_feclora\(\s*["']([a-z][a-z0-9_]*)["']""", tui_source))
        gtk_actions = set(re.findall(r"""["']([a-z][a-z0-9_]*)["']""", self.source))
        self.assertTrue(tui_actions, "Textual privileged action inventory must not be empty.")
        self.assertFalse(tui_actions - gtk_actions, f"GTK is missing Textual API actions: {sorted(tui_actions - gtk_actions)}")

    def test_welcome_uses_semantic_libadwaita_preference_groups(self):
        welcome = ast.get_source_segment(self.source, self.methods["_show_welcome"])
        for title in ("Idioma de la interfaz", "Distribución del teclado", "Acciones"):
            self.assertIn(title, welcome)
        self.assertEqual(welcome.count("Adw.PreferencesGroup("), 3)
        self.assertIn("Adw.ActionRow(", welcome)
        self.assertIn("self.keyboard_selection", welcome)
        self.assertIn("self.keyboard_dropdown.set_selected(", welcome)
        self.assertIn("set_activatable_widget", welcome)

    def test_welcome_callbacks_do_not_mutate_stale_widgets(self):
        welcome = ast.get_source_segment(self.source, self.methods["_show_welcome"])
        apply = ast.get_source_segment(self.source, self.methods["_apply_keyboard"])
        applied = ast.get_source_segment(self.source, self.methods["_keyboard_layout_applied"])
        terminal = ast.get_source_segment(self.source, self.methods["_open_root_terminal"])
        continue_method = ast.get_source_segment(self.source, self.methods["_continue"])
        self.assertIn('self._welcome_generation = getattr(self, "_welcome_generation", 0) + 1', welcome)
        self.assertIn('self._welcome_generation = getattr(self, "_welcome_generation", 0) + 1', continue_method)
        self.assertIn("welcome_generation = self._welcome_generation", apply)
        self.assertIn("_keyboard_layout_applied(layout, welcome_generation)", apply)
        self.assertIn("welcome_generation != self._welcome_generation", applied)
        self.assertIn("self.keyboard_layout = layout", applied)
        self.assertIn("self.toast_overlay.add_toast(", terminal)
        self.assertNotIn("self.status.set_text", terminal)

    def test_keyboard_layout_selection_is_preserved_after_apply(self):
        apply = ast.get_source_segment(self.source, self.methods["_apply_keyboard"])
        accepted = ast.get_source_segment(self.source, self.methods["_keyboard_layout_applied"])
        self.assertIn('"set_keyboard_layout"', apply)
        self.assertIn("_keyboard_layout_applied(layout)", apply)
        self.assertIn("self.keyboard_layout = layout", accepted)
        self.assertIn("self.keyboard_selection = layout", accepted)
        language = ast.get_source_segment(self.source, self.methods["_language_changed"])
        self.assertIn("self.keyboard_selection = KEYBOARD_LAYOUTS[keyboard_index][1]", language)
        self.assertIn("apply_ok", accepted)
    def test_capture_passphrase_is_not_retained_in_frontend_state(self):
        self.assertNotIn("_capture_requests", self.source)
        accepted = ast.get_source_segment(self.source, self.methods["_capture_accepted"])
        self.assertIn('"provide_capture_passphrase"', accepted)
        self.assertIn('"passphrase": passphrase', accepted)

    def test_capture_completion_refreshes_inventory_and_image_catalog(self):
        status = ast.get_source_segment(self.source, self.methods["_show_capture_status"])
        self.assertIn('status.get("operation_id") not in (None, operation_id)', status)
        self.assertIn('self._capture_action_errors[operation_id] = "El estado devuelto pertenece a otra operación."', status)
        terminal = status[status.index('if state in {"completed", "failed", "cancelled", "interrupted"}:'):]
        self.assertIn('if state == "completed":', terminal)
        self.assertIn('self.api.submit(\n                    "inventory"', terminal)
        self.assertIn("self._populate_capture_devices(response)", terminal)
        self.assertIn("self._capture_repository_changed(self.capture_repository, None)", terminal)

    def test_overview_uses_real_status_api(self):
        method = ast.get_source_segment(self.source, self.methods["_refresh_status"])
        self.assertIn('self.api.submit("status"', method)
        self.assertIn("_show_status", method)

    def test_inventory_uses_real_inventory_api_and_semantic_hierarchical_rows(self):
        method = ast.get_source_segment(self.source, self.methods["_refresh_inventory"])
        self.assertIn('self.api.submit("inventory"', method)
        flatten = ast.get_source_segment(self.source, self.methods["_flatten_devices"])
        self.assertIn('device.get("children")', flatten)
        render = ast.get_source_segment(self.source, self.methods["_show_inventory"])
        subtitle = ast.get_source_segment(self.source, self.methods["_inventory_device_subtitle"])
        append = ast.get_source_segment(self.source, self.methods["_append_inventory_device"])
        for field in ("type", "size_bytes", "model", "filesystem", "mountpoints"):
            self.assertIn(field, subtitle)
        self.assertIn("Adw.PreferencesGroup(", render)
        self.assertIn("Adw.StatusPage(", render)
        self.assertIn("Adw.ActionRow(", append)
        self.assertIn("device.get(\"children\")", append)
        self.assertIn("self._append_inventory_device(group, child, depth + 1)", append)
        self.assertNotIn("Gtk.Grid(", render)
        self.assertIn("_inventory_refresh_generation", method)
        self.assertIn("page_generation == self._page_generation", method)
        self.assertIn("generation != self._inventory_refresh_generation", render)

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
        page_select = ast.get_source_segment(self.source, self.methods["_select_page"])
        repository_change = ast.get_source_segment(self.source, self.methods["_capture_repository_changed"])
        self.assertIn("operations_page_generation = self._page_generation", page_select)
        self.assertIn("operations_page_generation == self._page_generation", page_select)
        self.assertIn("_capture_catalog_generation", repository_change)
        self.assertIn("generation == self._capture_catalog_generation", repository_change)
        self.assertIn('Gtk.StringList.new(["Cargando imágenes…"])', repository_change)

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

    def test_btrfs_operations_preserve_selected_repository(self):
        start = ast.get_source_segment(self.source, self.methods["_start_disk_capture"])
        self.assertEqual(start.count('params["repository_id"] = selected_repository["id"]'), 6)
        self.assertIn('self.api.submit("capture_btrfs_subvolume"', start)
        self.assertIn('self.api.submit("receive_btrfs_subvolume"', start)

    def test_remote_job_actions_include_refresh_and_preserve_action_mapping(self):
        page = ast.get_source_segment(self.source, self.methods["_show_remote_jobs_page"])
        action = ast.get_source_segment(self.source, self.methods["_run_remote_job_action"])
        self.assertIn('"Actualizar estado"', page)
        self.assertIn('("status", "start", "refresh", "arm", "cancel", "stop", "reconcile")', action)
        self.assertIn('action in {"status", "refresh"}', action)

    def test_pxe_answer_publication_supports_scp_over_sshfs(self):
        page = ast.get_source_segment(self.source, self.methods["_show_server_status_page"])
        publisher = ast.get_source_segment(self.source, self.methods["_publish_pxe_answer"])
        self.assertIn('"SCP · SSHFS"', page)
        self.assertIn('("upload", "url", "repository", "scp")[source_index] if source_index < 4', publisher)
        self.assertIn('source in {"repository", "scp"}', publisher)
        self.assertIn('repository.get("provider") != "sshfs"', publisher)
        self.assertIn('"repository_id"', publisher)
        self.assertIn('"source_path"', publisher)

    def test_remote_job_import_supports_scp_over_sshfs(self):
        page = ast.get_source_segment(self.source, self.methods["_show_remote_jobs_page"])
        importer = ast.get_source_segment(self.source, self.methods["_import_remote_job"])
        self.assertIn('"SCP · SSHFS"', page)
        self.assertIn('"scp"', importer)
        self.assertIn('("upload", "url", "repository", "scp")[source_index] if source_index < 4', importer)
        self.assertIn('source in {"repository", "scp"}', importer)
        self.assertIn('repository.get("provider") != "sshfs"', importer)
        self.assertIn('"repository_id"', importer)
        self.assertIn('"source_path"', importer)

    def test_operations_repository_selector_supports_local_remote_and_s3(self):
        remote = ast.get_source_segment(self.source, self.methods["_populate_capture_repositories"])
        s3 = ast.get_source_segment(self.source, self.methods["_populate_capture_s3_repositories"])
        finish = ast.get_source_segment(self.source, self.methods["_finish_capture_repository_loading"])
        changed = ast.get_source_segment(self.source, self.methods["_capture_repository_changed"])
        mode = ast.get_source_segment(self.source, self.methods["_capture_mode_changed"])
        self.assertIn('item.get("mounted") and item.get("verified")', remote)
        self.assertIn('self._capture_s3_repositories', s3)
        self.assertIn('{"id": None, "_kind": "local"}', finish)
        self.assertIn('{**item, "_kind": "s3"}', finish)
        self.assertIn('"repository_images"', changed)
        self.assertIn('self.capture_repository_label.set_visible(True)', mode)
        self.assertIn('"Repositorio de imágenes"', self.source)
        self.assertIn('self.capture_repository.connect("notify::selected", self._capture_repository_changed)', self.source)

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
        for action in ("capture_logical_volume", "capture_stratis_filesystem", "capture_btrfs_subvolume", "receive_btrfs_subvolume", "recover_disk", "finalize_recovery", "restore_disk", "restore_partition", "restore_logical_volume", "restore_stratis_filesystem", "clone_disk", "clone_partition", "build_recovery_iso", "build_deployment_bundle", "restore_proportional_disk", "capture_p2v", "execute_restore_profile"):
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
        self.assertIn('self.api.submit("verify_image"', self.source)
        self.assertIn('self.api.submit("extract_partition_image"', self.source)
        self.assertIn("base64.b64decode(encoded, validate=True)", self.source)
        self.assertIn("os.O_EXCL, 0o600", self.source)
        self.assertIn('os.fdopen(file_descriptor, "wb")', self.source)
        self.assertIn("self.image_layout", self.source)
        self.assertIn('self.api.submit("repository_images"', self.source)
        repository_loader = ast.get_source_segment(self.source, self.methods["_refresh_repositories"])
        self.assertIn("_repository_refresh_generation", repository_loader)
        self.assertIn("generation == self._repository_refresh_generation", repository_loader)
        repository_page = ast.get_source_segment(self.source, self.methods["_show_repositories_page"])
        self.assertIn("_repository_page_generation", repository_page)
        self.assertIn('self.image_session_id = result.get("session_id", "")', self.source)
        image_loader = ast.get_source_segment(self.source, self.methods["_load_image_catalog"])
        self.assertIn("_image_catalog_generation", image_loader)
        self.assertIn("generation == self._image_catalog_generation", image_loader)
        image_page = ast.get_source_segment(self.source, self.methods["_show_images_page"])
        self.assertIn("_image_page_generation", image_page)
        self.assertIn("self.image_catalog = []", image_page)
        self.assertIn("self.image_layout = None", image_page)
        self.assertIn("self.image_catalog = []", image_loader)
        self.assertIn('Gtk.StringList.new(["Cargando imágenes…"])', image_loader)
        inspect = ast.get_source_segment(self.source, self.methods["_inspect_selected_image"])
        self.assertLess(inspect.index("_reset_image_layout()"), inspect.index("self.api.submit("))
        self.assertIn("catalog_generation == self._image_catalog_generation", inspect)
        self.assertIn("page_generation == self._image_page_generation", inspect)
        browse = ast.get_source_segment(self.source, self.methods["_browse_selected_image"])
        self.assertIn("_image_browse_generation", browse)
        self.assertIn("catalog_generation == self._image_catalog_generation", browse)
        reset = ast.get_source_segment(self.source, self.methods["_reset_image_layout"])
        self.assertIn("_image_browse_generation", reset)
        partition_changed = ast.get_source_segment(self.source, self.methods["_image_partition_changed"])
        self.assertIn("_image_browse_generation", partition_changed)

    def test_proportional_restore_requires_smaller_target_and_kernel_identities(self):
        self.assertIn('"Restauración proporcional a disco menor"', self.source)
        self.assertIn('"restore_proportional_disk"', self.source)
        self.assertIn('source_device.get("major_minor")', self.source)
        self.assertIn('target_device.get("major_minor")', self.source)
        self.assertIn('target_device["size_bytes"] >= source_device["size_bytes"]', self.source)

    def test_remote_job_selector_backing_rows_exclude_missing_identifiers(self):
        method = ast.get_source_segment(self.source, self.methods["_populate_remote_job_controls"])
        self.assertIn('isinstance(item.get("job_id"), str)', method)
        self.assertIn('item.get("job_id").strip()', method)
        self.assertIn('for item in self._remote_jobs', method)
        self.assertNotIn('if item.get("job_id")', method)

    def test_system_page_restores_textual_configuration_service_and_certificate_details(self):
        page = ast.get_source_segment(self.source, self.methods["_show_system_page"])
        status = ast.get_source_segment(self.source, self.methods["_show_status"])
        self.assertIn("self.system_details_group = Adw.PreferencesGroup(", page)
        self.assertIn('status.get("server_configured")', status)
        self.assertIn('status.get("client_configured")', status)
        self.assertIn('status.get("services")', status)
        self.assertIn('status.get("certificate_status")', status)
        self.assertIn('Adw.ActionRow(title=name, subtitle=value)', status)

    def test_system_and_server_pages_render_service_certificate_and_pxe_status(self):
        self.assertIn('self.api.submit("pxe_service_status"', self.source)
        self.assertIn('self.api.submit("network_interfaces"', self.source)
        self.assertIn('status.get("certificate_status")', self.source)
        self.assertIn('def _show_system_page', self.source)
        self.assertIn('def _show_server_status_page', self.source)
        server_refresh = ast.get_source_segment(self.source, self.methods["_refresh_server_status"])
        server_part = ast.get_source_segment(self.source, self.methods["_server_status_part"])
        server_error = ast.get_source_segment(self.source, self.methods["_server_status_failed"])
        self.assertIn("_server_status_refresh_generation", server_refresh)
        self.assertIn("page_generation == self._server_status_page_generation", server_refresh)
        self.assertIn("generation != self._server_status_refresh_generation", server_part)
        self.assertIn("generation != self._server_status_refresh_generation", server_error)
        selected_server = ast.get_source_segment(self.source, self.methods["_selected_server_interface"])
        server_part = ast.get_source_segment(self.source, self.methods["_server_status_part"])
        self.assertIn("selected == 0", selected_server)
        self.assertIn("interfaces[selected - 1]", selected_server)
        self.assertIn('"Selecciona interfaz/dirección activa…"', server_part)

    def test_repository_page_lists_remote_and_s3_storage_state(self):
        self.assertIn('self.api.submit("remote_repositories"', self.source)
        self.assertIn('self.api.submit("s3_repositories"', self.source)
        self.assertIn('item.get("mounted")', self.source)
        self.assertIn('item.get("verified")', self.source)
        self.assertIn('item.get("read_only")', self.source)
        render = ast.get_source_segment(self.source, self.methods["_render_repositories"])
        self.assertIn("previous_key", render)
        self.assertIn("selected_index = next(", render)
        self.assertIn("self.repository_management.set_selected(selected_index)", render)
        self.assertIn('self._repository_refresh_pending_parts = {"remote", "s3"}', repository_loader)
        self.assertIn("self._repository_refresh_part_loaded", repository_loader)
        loaded = ast.get_source_segment(self.source, self.methods["_repository_refresh_part_loaded"])
        self.assertIn("if not pending", loaded)
        self.assertIn("self._render_repositories()", loaded)

    def test_repository_and_p2v_actions_are_page_and_request_scoped(self):
        page = ast.get_source_segment(self.source, self.methods["_show_repositories_page"])
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_repositories"])
        submit = ast.get_source_segment(self.source, self.methods["_submit_repository_action"])
        done = ast.get_source_segment(self.source, self.methods["_repository_action_done"])
        failed = ast.get_source_segment(self.source, self.methods["_repository_action_failed"])
        p2v_submit = ast.get_source_segment(self.source, self.methods["_submit_p2v_operation"])
        p2v_done = ast.get_source_segment(self.source, self.methods["_p2v_operation_accepted"])
        self.assertIn("self._repository_window_page_generation = self._page_generation", page)
        self.assertIn("window_generation == self._page_generation", refresh)
        self.assertIn("request_generation = self._repository_action_generation", submit)
        self.assertIn("self._repository_action_results.append(response)", done)
        self.assertIn("request_generation != self._repository_action_generation", failed)
        self.assertIn("request_generation = self._p2v_action_generation", p2v_submit)
        self.assertIn("self._p2v_operation_results[operation_id] = result", p2v_done)
        self.assertIn("window_generation != self._page_generation", p2v_done)

    def test_image_verification_download_and_extraction_callbacks_keep_identity(self):
        verify = ast.get_source_segment(self.source, self.methods["_verify_selected_image"])
        verified = ast.get_source_segment(self.source, self.methods["_show_image_verification"])
        inspect = ast.get_source_segment(self.source, self.methods["_inspect_selected_image"])
        inspected = ast.get_source_segment(self.source, self.methods["_show_image_layout"])
        download = ast.get_source_segment(self.source, self.methods["_save_image_download"])
        extract = ast.get_source_segment(self.source, self.methods["_extract_selected_partition"])
        accepted = ast.get_source_segment(self.source, self.methods["_image_extraction_accepted"])
        poll = ast.get_source_segment(self.source, self.methods["_poll_image_extraction"])
        status = ast.get_source_segment(self.source, self.methods["_show_image_extraction_status"])
        page = ast.get_source_segment(self.source, self.methods["_show_images_page"])
        self.assertIn("request_generation = self._image_verification_generation", verify)
        self.assertIn("self._image_verification_results[(repository_id, image_id)] = result", verified)
        self.assertIn("request_generation = self._image_inspection_generation", inspect)
        self.assertIn("self._image_inspection_results[(repository_id, image_id)] = layout", inspected)
        self.assertIn("self._image_repository_id() != repository_id", inspected)
        self.assertIn("self._image_download_results.append(str(destination))", download)
        self.assertIn("download_generation == self._image_download_generation", download)
        self.assertIn("request_generation = self._image_action_generation", extract)
        self.assertIn('self._image_operation_results[operation_id] = {"accepted": result, "status": None}', accepted)
        self.assertIn('{"operation_id": operation_id}', poll)
        self.assertIn('self._image_operation_results.setdefault(operation_id, {})["status"] = status', status)
        self.assertIn("_poll_image_extraction(pending_operation_id, page_generation, window_generation)", page)
        self.assertIn("window_generation != self._page_generation", status)

    def test_p2v_operations_are_polled_to_terminal_state_and_resumed(self):
        page = ast.get_source_segment(self.source, self.methods["_show_repositories_page"])
        accepted = ast.get_source_segment(self.source, self.methods["_p2v_operation_accepted"])
        poll = ast.get_source_segment(self.source, self.methods["_poll_p2v_operation"])
        loaded = ast.get_source_segment(self.source, self.methods["_p2v_operation_status_loaded"])
        failed = ast.get_source_segment(self.source, self.methods["_p2v_operation_status_failed"])
        self.assertIn("_latest_p2v_operation_id", page)
        self.assertIn("_poll_p2v_operation(", page)
        self.assertIn("self._latest_p2v_operation_id = operation_id", accepted)
        self.assertLess(accepted.index("self._latest_p2v_operation_id = operation_id"), accepted.index("if page_generation != self._repository_page_generation"))
        self.assertIn('"local_operation_status", {"operation_id": operation_id}', poll)
        self.assertIn('self._p2v_operation_results.setdefault(operation_id, {})["status"] = status', loaded)
        self.assertIn('{"completed", "failed", "cancelled", "interrupted"}', loaded)
        self.assertIn('if state == "completed":\n                self._refresh_repositories(None)', loaded)
        self.assertIn("self._p2v_view_is_current(page_generation, window_generation, operation_id)", loaded)
        self.assertIn("self._p2v_operation_errors[operation_id] = \"status: \" + str(error)", failed)

    def test_image_browse_failure_invalidates_session_without_failing_catalog(self):
        browse = ast.get_source_segment(self.source, self.methods["_browse_selected_image"])
        failed = ast.get_source_segment(self.source, self.methods["_image_browse_failed"])
        self.assertIn("self._image_browse_failed(error, page_generation, window_generation, catalog_generation, browse_generation)", browse)
        self.assertIn('self.image_session_id = ""', failed)
        self.assertIn('self.image_listing.set_text("")', failed)
        self.assertIn("browse_generation != self._image_browse_generation", failed)
        self.assertNotIn("image_catalog_stack.set_visible_child_name", failed)

    def test_image_download_errors_and_feedback_are_bound_to_exact_selection(self):
        download = ast.get_source_segment(self.source, self.methods["_download_selected_image_file"])
        failed = ast.get_source_segment(self.source, self.methods["_image_download_failed"])
        saved = ast.get_source_segment(self.source, self.methods["_save_image_download"])
        current = ast.get_source_segment(self.source, self.methods["_image_download_is_current"])
        self.assertIn("image_id = (self._selected_image() or {}).get(\"image_id\")", download)
        self.assertIn("repository_id = self._image_repository_id()", download)
        self.assertIn("self._image_download_failed(error", download)
        self.assertIn("self._image_download_is_current(", failed)
        self.assertIn("self._image_download_is_current(", saved)
        self.assertIn("self._image_repository_id() == repository_id", current)
        self.assertIn("(self._selected_image() or {}).get(\"image_id\") == image_id", current)

    def test_remote_deployment_and_client_history_pages_use_persistent_api(self):
        for action in ('self.api.submit(action, on_success=lambda response: self._show_history_rows', 'self.api.submit("deployment_jobs"', 'self._history_page("Historial de despliegues', 'self._history_page("Trabajos remotos'):
            self.assertIn(action, self.source)
        self.assertIn('"journals", "journals"', self.source)
        remote_page = ast.get_source_segment(self.source, self.methods["_show_remote_jobs_page"])
        self.assertIn("_remote_jobs_page_generation", remote_page)
        self.assertIn('self._remote_import_pending_parts = {"remote", "s3"}', remote_page)
        remote_loaded = ast.get_source_segment(self.source, self.methods["_remote_import_repository_part_loaded"])
        self.assertIn("if not pending", remote_loaded)
        self.assertIn("self._render_remote_import_repositories()", remote_loaded)
        self.assertIn('details.get("state")', self.source)
        history_page = ast.get_source_segment(self.source, self.methods["_history_page"])
        history_refresh = ast.get_source_segment(self.source, self.methods["_refresh_history"])
        self.assertIn("_history_page_generation", history_page)
        self.assertIn("_history_refresh_generation", history_refresh)
        self.assertIn("page_generation == self._page_generation", history_refresh)
        self.assertIn("generation == self._history_refresh_generation", history_refresh)

    def test_operation_log_and_ddrescue_history_use_persistent_api_records(self):
        self.assertIn('self.api.submit("local_operations"', self.source)
        self.assertIn('self.api.submit("cancel_local_operation"', self.source)
        profile_loader = ast.get_source_segment(self.source, self.methods["_load_restore_profiles_for_repository"])
        self.assertIn("_profile_repository_generation", profile_loader)
        self.assertIn("generation == self._profile_repository_generation", profile_loader)
        self.assertIn('operation_confirmation.get_text() != expected', self.source)
        self.assertIn('self.api.submit("recovery_jobs"', self.source)
        self.assertIn('details.get("destination_may_be_partial")', self.source)
        self.assertIn('item.get("unresolved_bytes")', self.source)
        self.assertIn('item.get("progress_percent")', self.source)
        operation_refresh = ast.get_source_segment(self.source, self.methods["_refresh_operation_log"])
        recovery_refresh = ast.get_source_segment(self.source, self.methods["_refresh_recovery_jobs"])
        self.assertIn("generation == self._operation_log_refresh_generation", operation_refresh)
        self.assertIn("page_generation == self._page_generation", operation_refresh)
        self.assertIn("generation == self._recovery_jobs_refresh_generation", recovery_refresh)
        self.assertIn("page_generation == self._page_generation", recovery_refresh)

    def test_operation_log_displays_each_inspection_error_in_current_page_group(self):
        page = ast.get_source_segment(self.source, self.methods["_show_operation_log_page"])
        render = ast.get_source_segment(self.source, self.methods["_show_operation_log"])
        self.assertIn('self.operation_log_inspection_group = Adw.PreferencesGroup(', page)
        self.assertIn('self.page_body.append(self.operation_log_inspection_group)', page)
        self.assertIn('response.get("inspection_errors")', render)
        self.assertIn('self.operation_log_inspection_group', render)
        self.assertIn('error_group.add(Adw.ActionRow(title=str(path), subtitle=str(reason)))', render)
        self.assertIn('No repitas operaciones afectadas', render)

    def test_network_page_uses_active_profiles_and_validated_ipv4_checkpoint(self):
        for action in ('self.api.submit("network_connection_profiles"', 'self.api.submit("network_interfaces"', 'self.api.submit("apply_network_profile"'):
            self.assertIn(action, self.source)
        self.assertIn('ipaddress.IPv4Address(self.network_address.get_text().strip())', self.source)
        self.assertIn('"rollback_timeout": 120', self.source)
        self.assertIn('interface.get("interface") != profile.get("device")', self.source)
        profiles = ast.get_source_segment(self.source, self.methods["_populate_network_profiles"])
        interfaces = ast.get_source_segment(self.source, self.methods["_update_network_interface_options"])
        apply = ast.get_source_segment(self.source, self.methods["_apply_network_profile"])
        self.assertIn('"Selecciona perfil activo…"', profiles)
        self.assertIn('"Selecciona interfaz y dirección…"', interfaces)
        self.assertIn("index - 1", interfaces)
        self.assertIn("profile_index == 0", apply)
        self.assertIn("interface_index == 0", apply)
        network_page = ast.get_source_segment(self.source, self.methods["_show_network_page"])
        applied = ast.get_source_segment(self.source, self.methods["_network_applied"])
        self.assertIn("_network_page_generation", network_page)
        self.assertIn("page_generation == self._network_page_generation", network_page)
        self.assertIn("current_generation == self._network_page_generation", applied)
        self.assertIn("self.network_active_profiles = []", network_page)
        self.assertIn("self.network_interfaces = []", network_page)
        self.assertIn("self.network_interface_records = []", applied)
        self.assertIn('Gtk.StringList.new(["Cargando perfiles…"])', applied)

    def test_restore_profiles_are_bound_to_stable_disk_identity_and_single_use_confirmation(self):
        for action in ('self.api.submit("restore_profiles"', 'self.api.submit("create_restore_profile"', 'self.api.submit("execute_restore_profile"'):
            self.assertIn(action, self.source)
        self.assertIn('item.get("wwn") or item.get("serial")', self.source)
        self.assertIn('"target_wwn": target.get("wwn")', self.source)
        self.assertIn('"target_serial": target.get("serial")', self.source)
        self.assertIn('profile.get("consumed")', self.source)
        self.assertIn('self.profile_confirmation.get_text() != expected', self.source)
        self.assertIn('self.api.submit("cancel_local_operation"', self.source)

    def test_p2v_capture_uses_disk_inventory_and_qcow2_conversion_api(self):
        self.assertIn('"Capturar disco virtual QCOW2 (P2V)"', self.source)
        self.assertIn('self.api.submit("capture_p2v"', self.source)
        self.assertIn('params = {"source": self.capture_devices[index]["path"], "image_id": image_id}', self.source)

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

    def test_legacy_p2v_import_and_s3_export_are_available_in_gtk(self):
        self.assertIn('Compatibilidad P2V heredada', self.source)
        self.assertIn('def _import_legacy_p2v', self.source)
        self.assertIn('def _export_legacy_p2v', self.source)
        self.assertIn('self._submit_p2v_operation("import_p2v"', self.source)
        self.assertIn('self._submit_p2v_operation("export_p2v_s3"', self.source)
        self.assertIn('"source_image_id": source_image_id', self.source)
        self.assertIn('"source_repository_id": sources[source_index - 1]["id"]', self.source)
        self.assertIn('params["destination_repository_id"]', self.source)
        self.assertIn('self.p2v_import_repository', self.source)
        self.assertIn('self.p2v_export_repository', self.source)
        self.assertIn('self.p2v_result.set_text', self.source)

    def test_pxe_answer_s3_repository_selector_includes_configured_s3_without_mount_flags(self):
        start = self.source.index("    def _pxe_answer_s3_repositories")
        end = self.source.index("    def _render_pxe_answer_repositories", start)
        method = self.source[start:end]
        self.assertIn('item for item in response.get("repositories", [])', method)
        self.assertIn('isinstance(item, dict) and item.get("id")', method)
        self.assertNotIn('item.get("mounted")', method)
        self.assertNotIn('item.get("verified")', method)
        pxe_loader = ast.get_source_segment(self.source, self.methods["_refresh_pxe_answer_repositories"])
        pxe_loaded = ast.get_source_segment(self.source, self.methods["_pxe_answer_repository_part_loaded"])
        self.assertIn('self._pxe_answer_pending_parts = {"remote", "s3"}', pxe_loader)
        self.assertIn("page_generation == self._server_status_page_generation", pxe_loader)
        self.assertIn("if not pending", pxe_loaded)
        self.assertIn("self._render_pxe_answer_repositories()", pxe_loaded)

    def test_repository_management_and_credential_controls_use_allowlisted_api(self):
        for action in (
            '"check": "check_s3_repository"',
            '"remove": "remove_s3_repository"',
            '"check": "check_remote_repository"',
            '"mount": "mount_remote_repository"',
            '"unmount": "unmount_remote_repository"',
            '"remove": "remove_remote_repository"',
            'self.api.submit("systemd_credentials"',
            'self._submit_repository_action("put_systemd_credential"',
            'self._submit_repository_action("remove_systemd_credential"',
        ):
            self.assertIn(action, self.source)
        self.assertIn('mount_state != "unmounted"', self.source)
        self.assertIn('mount_state != "identity_verified"', self.source)
        self.assertIn('f"REMOVE {identifier}"', self.source)
        self.assertIn('credential_management', self.source)
        self.assertIn('repository_management_rows', self.source)
        self.assertIn('f"Definición {provider} cargada; guarda los cambios en el formulario."', self.source)
        self.assertIn('Definición S3 cargada', self.source)
        self.assertIn('self.remote_id.set_editable(False)', self.source)
        self.assertIn('self.s3_id.set_editable(False)', self.source)
        self.assertIn('self.remote_id.set_editable(True)', self.source)
        self.assertIn('self.s3_id.set_editable(True)', self.source)
        self.assertIn('action = "update_remote_repository" if existing else "add_remote_repository"', self.source)
        self.assertIn('action = "update_s3_repository" if existing else "add_s3_repository"', self.source)
        self.assertIn('self.s3_credential = Gtk.DropDown.new_from_strings(["Selecciona credencial S3…"] )', self.source)
        self.assertIn('def _populate_s3_credential_selector', self.source)
        self.assertIn('def _selected_s3_credential_id', self.source)
        self.assertIn('credential_id = self._selected_s3_credential_id()', self.source)
        self.assertIn('previous_id = self._selected_s3_credential_id()', self.source)
        self.assertIn('if item.get("id") == previous_id', self.source)
        self.assertIn('previous_path = (', self.source)
        self.assertIn('if item.get("path") == previous_path', self.source)
        self.assertIn('self._submit_repository_action(api_action', self.source)
        self.assertIn('self.api.submit(action, params', self.source)

    def test_server_bootstrap_tls_and_pxe_controls_use_existing_api_contracts(self):
        for action in (
            'self.api.submit("bootstrap_server"',
            'self.api.submit("renew_server_certificate"',
            'self.api.submit("rotate_server_keypair"',
            'self.api.submit("validate_pxe_profile"',
            'self.api.submit("start_pxe_services"',
            'self.api.submit("stop_pxe_services"',
        ):
            self.assertIn(action, self.source)
        self.assertIn('"interface": selected.get("interface")', self.source)
        self.assertIn('"prefix_length": selected.get("prefix_length")', self.source)
        self.assertIn('"RENEW SERVER CERTIFICATE"', self.source)
        self.assertIn('"ROTATE SERVER TLS KEYPAIR"', self.source)
        self.assertIn('"authoritative_confirmed": self.pxe_authoritative.get_active()', self.source)
        self.assertIn('self.pxe_mode.connect("notify::selected", self._pxe_mode_changed)', self.source)
        self.assertIn('def _pxe_mode_changed(self, _widget: Gtk.DropDown', self.source)
        self.assertIn('self.pxe_pool_start_row, self.pxe_pool_end_row', self.source)
        self.assertIn('row.set_visible(isolated)', self.source)
        self.assertIn('self._pxe_profile = None', self.source)
        self.assertIn('self.pxe_start.set_sensitive(False)', self.source)
        self.assertIn('self._pxe_pending_profile = profile', self.source)
        invalidate = ast.get_source_segment(self.source, self.methods["_invalidate_pxe_validation"])
        mode_changed = ast.get_source_segment(self.source, self.methods["_pxe_mode_changed"])
        validate = ast.get_source_segment(self.source, self.methods["_validate_pxe_profile"])
        self.assertIn("_pxe_validation_generation", invalidate)
        self.assertIn("self._pxe_pending_profile = None", invalidate)
        self.assertIn("self._invalidate_pxe_validation()", mode_changed)
        self.assertIn("token=generation", validate)
        self.assertIn("window_generation = self._server_window_page_generation", validate)
        self.assertIn('self.pxe_authoritative.connect("toggled", self._pxe_inputs_changed)', self.source)
        self.assertIn('self.pxe_start.set_sensitive(False)', self.source)

    def test_pxe_answer_publication_revocation_and_age_workflows(self):
        for action in (
            'self.api.submit("publish_pxe_answer"',
            'self.api.submit("revoke_pxe_answer"',
            'self.api.submit("pxe_age_passphrase_status"',
            'self.api.submit("provide_pxe_age_passphrase"',
            'self.api.submit("export_server_age_recipients"',
            'self.api.submit("refresh_client_age_recipients"',
        ):
            self.assertIn(action, self.source)
        self.assertIn('"source": source', self.source)
        self.assertIn('"answer_base64": base64.b64encode(payload).decode("ascii")', self.source)
        self.assertIn('request["repository_id"]', self.source)
        self.assertIn('request["source_path"]', self.source)
        self.assertIn('self.pxe_answer_revoke_id.set_text(job_id)', self.source)
        publisher = ast.get_source_segment(self.source, self.methods["_pxe_answer_published"])
        revoker = ast.get_source_segment(self.source, self.methods["_pxe_answer_revoked"])
        self.assertIn("self._pxe_published_answer = result", publisher)
        self.assertIn("result.get(\"job_id\") or requested_job_id", publisher)
        self.assertIn("self._pxe_published_answer = None", revoker)
        self.assertIn('self.pxe_passphrase.set_visibility(False)', self.source)
        self.assertIn('self.pxe_passphrase.set_text("")', self.source)
        self.assertIn('self.pxe_passphrase.set_sensitive(False)', self.source)

    def test_remote_deployment_definition_import_and_lifecycle_actions(self):
        for action in (
            'self.api.submit("deployment_jobs"',
            'self.api.submit("remote_repositories"',
            'self.api.submit("s3_repositories"',
            'self.api.submit("create_deployment_job"',
            'self.api.submit("import_deployment_job"',
            'self.api.submit("deployment_service_status"',
            'self.api.submit("start_deployment_service"',
            'self.api.submit("arm_deployment_job"',
            'self.api.submit("cancel_deployment_job"',
            'self.api.submit("stop_deployment_service"',
            'self.api.submit("reconcile_deployment_job"',
        ):
            self.assertIn(action, self.source)
        self.assertIn('f"ARM PHYSICAL MULTICAST {job_id}', self.source)
        self.assertIn('f"ARM MULTICAST {job_id}', self.source)
        self.assertIn('f"CANCEL {job_id}"', self.source)
        self.assertIn('f"RECONCILE {job_id}"', self.source)
        self.assertIn('job.get("interrupted") or job.get("job_state") != "created"', self.source)
        self.assertIn('def _stop_remote_job_after_status', self.source)
        self.assertIn('self.remote_job_json.get_buffer().set_text', self.source)

    def test_authenticated_client_inspection_start_and_status_workflows(self):
        for action in (
            'self.api.submit("network_interfaces"',
            'self.api.submit("inventory"',
            'self.api.submit("inspect_remote_job"',
            'self.api.submit("start_client_job"',
            'self.api.submit("client_job_status"',
        ):
            self.assertIn(action, self.source)
        self.assertIn('"network_interface": interface["interface"]', self.source)
        self.assertIn('"source_address": interface["address"]', self.source)
        self.assertIn('f"ERASE {target}"', self.source)
        self.assertIn('f"READ {target} TO {inspection.get(\'server_identity\')}"', self.source)
        self.assertIn('self.client_confirmation.get_text()', self.source)
        self.assertIn('self.client_igmp.get_active() if job.get("transport") == "multicast" else False', self.source)
        self.assertIn('self._client_logical_volumes', self.source)
        self.assertIn('self._client_eligible_targets', self.source)
        client_page = ast.get_source_segment(self.source, self.methods["_show_client_jobs_page"])
        inspection = ast.get_source_segment(self.source, self.methods["_inspect_client_job"])
        invalidation = ast.get_source_segment(self.source, self.methods["_invalidate_client_inspection"])
        self.assertIn("_client_page_generation", client_page)
        self.assertIn("self.client_server_host.connect(\"changed\", self._client_inputs_changed)", client_page)
        self.assertIn("generation == self._client_inspection_generation", inspection)
        self.assertIn("self._client_remote_inspection = None", invalidation)
        self.assertIn("self.client_target.set_selected(0)", invalidation)
        self.assertIn("self._invalidate_client_inspection()", self.source)

    def test_remote_repository_selector_handles_async_source_completion_order(self):
        self.assertIn('self._remote_import_remote_rows =', self.source)
        self.assertIn('self._remote_import_s3_rows =', self.source)
        self.assertIn('getattr(self, "_remote_import_remote_rows", []) + getattr(self, "_remote_import_s3_rows", [])', self.source)
        self.assertIn('def _update_client_inventory_summary', self.source)

    def test_remote_repository_provider_forms_cover_sshfs_nfs_and_smb(self):
        for token in (
            'Gtk.DropDown.new_from_strings(["SSHFS", "NFS", "SMB/CIFS"])',
            'self._remote_provider_changed(self.remote_provider)',
            'self.remote_identity.set_visible(provider == "sshfs")',
            'self.remote_credential.set_visible(provider == "smb")',
            '"provider": provider',
            '"credential_file": credential_file',
            '"identity_file": identity_file',
            '"known_hosts_file": known_hosts_file',
            'self._selected_remote_credential_path(self.remote_credential, "_remote_smb_credentials")',
        ):
            self.assertIn(token, self.source)
        self.assertIn('SSHFS requiere usuario, clave privada y known_hosts protegidos.', self.source)
        self.assertIn('SMB/CIFS requiere usuario y credencial cifrada.', self.source)
        self.assertIn('{"sshfs": 0, "nfs": 1, "smb": 2}', self.source)

    def test_server_administration_uses_libadwaita_preferences_groups(self):
        start = self.source.index("    def _show_server_status_page")
        end = self.source.index("\n    def ", start + 10)
        page = self.source[start:end]
        self.assertGreaterEqual(page.count("Adw.PreferencesGroup("), 4)
        for title in (
            'title="Estado del servidor"',
            'title="Identidad y certificados TLS"',
            'title="Servicios PXE"',
            'title="Respuestas PXE desatendidas"',
            'title="Cifrado age y destinatarios"',
        ):
            self.assertIn(title, page)
        self.assertIn("def add_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget)", page)
        self.assertIn("row.add_suffix(widget)", page)
        self.assertIn("row.set_activatable_widget(widget)", page)
        self.assertIn('self.pxe_passphrase.set_visibility(False)', page)
        self.assertIn("self.pxe_start.set_sensitive(False)", page)
        self.assertIn('self._refresh_server_status(None)', page)
        for action in (
            'self._bootstrap_server',
            'self._renew_server_certificate',
            'self._rotate_server_keypair',
            'self._validate_pxe_profile',
            'self._start_pxe_services',
            'self._stop_pxe_services',
            'self._publish_pxe_answer',
            'self._revoke_pxe_answer',
            'self._export_server_age_recipients',
            'self._refresh_client_age_recipients',
            'self._submit_pxe_passphrase',
        ):
            self.assertIn(action, page)

    def test_system_status_uses_libadwaita_preferences_rows(self):
        start = self.source.index("    def _show_system_page")
        end = self.source.index("    def _show_server_status_page", start)
        page = self.source[start:end]
        self.assertIn("Adw.PreferencesGroup(", page)
        self.assertIn('title="Estado del sistema"', page)
        self.assertIn('status_row = Adw.ActionRow(title="Resumen del sistema")', page)
        self.assertIn("status_row.add_suffix(self.status_summary)", page)
        self.assertIn('refresh_row = Adw.ActionRow(title="Actualizar estado")', page)
        self.assertIn("refresh_row.set_activatable_widget(refresh)", page)
        self.assertIn("self._refresh_status(None)", page)
        refresh_status = ast.get_source_segment(self.source, self.methods["_refresh_status"])
        show_status = ast.get_source_segment(self.source, self.methods["_show_status"])
        select_page = ast.get_source_segment(self.source, self.methods["_select_page"])
        self.assertIn("_status_refresh_generation", refresh_status)
        self.assertIn("page_generation == self._page_generation", refresh_status)
        self.assertIn("generation != self._status_refresh_generation", show_status)
        self.assertIn("_page_generation", select_page)

    def test_image_catalog_uses_libadwaita_loading_empty_and_error_states(self):
        self.assertIn("self.image_catalog_stack = Gtk.Stack()", self.source)
        self.assertIn('Adw.StatusPage(\n            title="No hay imágenes de disco"', self.source)
        self.assertIn('Adw.StatusPage(\n            title="Cargando catálogo"', self.source)
        self.assertIn('Adw.StatusPage(\n            title="No se pudo cargar el catálogo"', self.source)
        self.assertIn('self.image_catalog_stack.set_visible_child_name("loading")', self.source)
        self.assertIn('self.image_catalog_stack.set_visible_child_name("images" if self.image_catalog else "empty")', self.source)
        self.assertIn('self.image_catalog_stack.set_visible_child_name("error")', self.source)
        self.assertIn('self.image_select.set_model(Gtk.StringList.new(labels or []))', self.source)

    def test_network_configuration_uses_native_libadwaita_controls(self):
        page = ast.get_source_segment(self.source, self.methods["_show_network_page"])
        self.assertIn('Adw.PreferencesGroup(\n            title="Conexión IPv4"', page)
        self.assertIn("def add_network_combo(title: str, labels: list[str]) -> Adw.ComboRow:", page)
        self.assertIn("def add_network_entry(title: str) -> Adw.EntryRow:", page)
        self.assertEqual(page.count("add_network_combo("), 4)
        self.assertEqual(page.count("add_network_entry("), 5)
        self.assertNotIn("Gtk.DropDown", page)
        self.assertNotIn("Gtk.Entry", page)
        self.assertIn("self.network_address_row = self.network_address", page)
        self.assertIn("self.network_dns_row = self.network_dns", page)
        self.assertIn("self._network_method_changed(self.network_method, None)", page)
        self.assertIn("for row in (self.network_address_row, self.network_prefix_row, self.network_gateway_row, self.network_dns_row):", self.source)
        self.assertIn("row.set_visible(manual)", self.source)

    def test_operation_and_recovery_histories_use_libadwaita_empty_states(self):
        self.assertIn("self.operation_log_stack = Gtk.Stack()", self.source)
        self.assertIn('Adw.StatusPage(\n            title="Sin operaciones registradas"', self.source)
        self.assertIn('self.operation_log_stack.set_visible_child_name("records" if operations else "empty")', self.source)
        self.assertIn("self.recovery_jobs_stack = Gtk.Stack()", self.source)
        self.assertIn('Adw.StatusPage(\n            title="Sin trabajos de recuperación"', self.source)
        self.assertIn('self.recovery_jobs_stack.set_visible_child_name("jobs" if jobs else "empty")', self.source)
        self.assertIn('self.operation_log_empty.set_title("No se pudo consultar el registro")', self.source)
        self.assertIn('self.operation_log_empty.set_title("Sin operaciones registradas")', self.source)
        self.assertIn('self.recovery_jobs_empty.set_title("No se pudieron consultar los trabajos")', self.source)
        self.assertIn('self.recovery_jobs_empty.set_title("Sin trabajos de recuperación")', self.source)

    def test_navigation_content_is_scrollable_for_full_operator_forms(self):
        self.assertIn("page_scroller = Gtk.ScrolledWindow()", self.source)
        self.assertIn("page_scroller.set_child(self.page_body)", self.source)

    def test_kiosk_window_is_fullscreen_and_not_decorated_or_closable(self):
        self.assertIn("self.window.fullscreen()", self.source)
        self.assertIn("self.window.set_decorated(False)", self.source)
        self.assertIn('self.window.connect("close-request"', self.source)


    def test_remote_job_and_deployment_histories_use_libadwaita_rows(self):
        start = self.source.index("    def _history_page")
        end = self.source.index("    def _show_remote_jobs_page", start)
        history = self.source[start:end]
        self.assertIn('title="Consulta del historial"', history)
        self.assertIn('summary_row = Adw.ActionRow(title="Estado"', history)
        self.assertIn('refresh_row.set_activatable_widget(refresh)', history)

        start = self.source.index("    def _show_remote_jobs_page")
        end = self.source.index("    def _show_deployments_page", start)
        remote = self.source[start:end]
        for title in ("Definición del trabajo", "Importar definición", "Servicio de despliegue"):
            self.assertIn(f'title="{title}"', remote)
        self.assertIn("job_row.set_activatable_widget(self.remote_job_select)", remote)
        self.assertIn("confirmation_row.set_activatable_widget(self.remote_job_confirmation)", remote)
        self.assertIn('self.api.submit("deployment_jobs"', remote)
        self.assertIn('self.api.submit("remote_repositories"', remote)
        self.assertIn('self.api.submit("s3_repositories"', remote)

    def test_client_job_history_uses_libadwaita_rows_without_changing_client_actions(self):
        start = self.source.index("    def _show_client_jobs_page")
        end = self.source.index("    def _show_client_job_rows", start)
        page = self.source[start:end]
        self.assertIn('title="Historial de clientes"', page)
        self.assertIn("client_refresh_row.set_activatable_widget(refresh)", page)
        for callback in ("self._inspect_client_job", "self._start_client_job", "self._refresh_client_job_status"):
            self.assertIn(callback, page)
        self.assertIn('self.api.submit("network_interfaces"', page)
        self.assertIn('self.api.submit("inventory"', page)


    def test_local_operations_use_semantic_libadwaita_groups(self):
        start = self.source.index('elif page_id == "operations":')
        end = self.source.index('        else:\n            self.page_description.set_text("Esta pantalla aún no se ha migrado.', start)
        page = self.source[start:end]
        for title in (
            "Inventario y selección de operación",
            "Origen, destino e imagen",
            "Confirmación y generación",
            "Btrfs",
            "Formato y protección",
            "Recuperación ddrescue",
            "Ejecución y seguimiento",
        ):
            self.assertIn(title, page)
        for widget in (
            "self.capture_kind", "self.capture_source", "self.capture_target",
            "self.capture_image_select", "self.capture_confirmation",
            "self.capture_repository", "self.capture_passphrase",
            "self.capture_btrfs_source", "self.capture_btrfs_target",
            "self.capture_retry", "self.capture_resume", "self.capture_start",
            "self.capture_cancel", "self.capture_progress", "self.capture_result",
        ):
            self.assertIn(widget, page)
        for callback in ("self._capture_mode_changed", "self._start_disk_capture", "self._cancel_disk_capture"):
            self.assertIn(callback, page)
        self.assertIn('self.capture_confirmation.set_placeholder_text("ERASE /dev/… o BUILD <imagen>")', page)
        hint = ast.get_source_segment(self.source, self.methods["_update_capture_confirmation_hint"])
        self.assertIn('self.capture_target.connect("notify::selected", self._update_capture_confirmation_hint)', page)
        self.assertIn('self.capture_image_select.connect("notify::selected", self._update_capture_confirmation_hint)', page)
        self.assertIn("self._update_capture_image_options()", self.source)
        self.assertIn('13: "stratis_filesystem"', self.source)
        self.assertIn('16: "disk"', self.source)
        self.assertIn('item.get("image_type") == expected_type', self.source)
        self.assertIn("self.capture_selectable_images[image_index]", self.source)
        self.assertNotIn('len(getattr(self, "capture_images", []))', self.source)
        self.assertNotIn('image = self.capture_images[image_index]', self.source)
        self.assertIn('phrase = "ERASE " + target', hint)
        self.assertIn('phrase += " FROM " + source', hint)
        self.assertIn('phrase = "BUILD " + str(images[index].get("image_id") or "")', hint)
        self.assertIn('self.capture_passphrase = Gtk.PasswordEntry()', page)
        self.assertIn("self.capture_btrfs_source_row.set_visible(is_btrfs_capture)", self.source)
        self.assertIn("self.capture_retry_row.set_visible(is_recovery)", self.source)
        self.assertIn('self.capture_retry = Gtk.DropDown.new_from_strings(["3"])', self.source)
        self.assertIn('"retry_passes": 3', self.source)
        self.assertNotIn('"retry_passes": self.capture_retry.get_selected()', self.source)
        self.assertIn("self.capture_image_id_label.set_title(", self.source)
        self.assertIn("image_id_visible = not (is_restore or is_clone or is_image_build or is_finalize)", self.source)
        self.assertIn("self.capture_image_id.set_visible(image_id_visible)", self.source)

    def test_repository_controls_use_semantic_libadwaita_groups(self):
        start = self.source.index("    def _show_repositories_page")
        end = self.source.index("    def _refresh_repositories", start)
        page = self.source[start:end]
        for title in (
            "Estado de los repositorios",
            "Compatibilidad P2V heredada",
            "Gestión de repositorios",
            "Repositorios SSHFS, NFS y SMB/CIFS",
            "Repositorios S3",
            "Credenciales systemd cifradas",
        ):
            self.assertIn(title, page)
            self.assertIn('Adw.PreferencesGroup(title=title', page)
        for widget in (
            "self.remote_provider", "self.remote_identity", "self.remote_known_hosts",
            "self.remote_credential", "self.s3_credential", "self.credential_source",
            "self.repository_confirmation", "self.credential_confirmation",
        ):
            self.assertIn(f"add_row(", page)
            self.assertIn(widget, page)
        for callback in (
            "self._refresh_repositories", "self._run_repository_action",
            "self._save_ssh_repository", "self._save_s3_repository",
            "self._import_repository_credential", "self._remove_repository_credential",
            "self._remote_provider_changed",
        ):
            self.assertIn(callback, page)
        self.assertIn('self.remote_credential.set_visible(provider == "smb")', self.source)
        self.assertIn('self.remote_identity.set_visible(provider == "sshfs")', self.source)

    def test_overview_uses_semantic_libadwaita_status_groups(self):
        start = self.source.index('        if page_id == "overview":')
        end = self.source.index('        elif page_id == "inventory":', start)
        page = self.source[start:end]
        for title in (
            "Identidad del equipo",
            "Configuración de Feclora",
            "Servicios del sistema",
            "Acciones",
        ):
            self.assertIn(f'title="{title}"', page)
            self.assertIn("Adw.PreferencesGroup(", page)
        for widget in ("self.status_summary", "self.overview_configuration", "self.overview_services"):
            self.assertIn(widget, page)
        self.assertIn("refresh_row.set_activatable_widget(refresh)", page)
        self.assertIn('self.api.submit("status"', self.source)
        status_start = self.source.index("    def _show_status")
        status_end = self.source.index("    @staticmethod", status_start)
        status_callback = self.source[status_start:status_end]
        self.assertIn("self.overview_configuration.set_text(", status_callback)
        self.assertIn("self.overview_services.set_text(", status_callback)
        self.assertIn("server_configured", status_callback)
        self.assertIn("client_configured", status_callback)

    def test_images_page_uses_semantic_libadwaita_groups(self):
        start = self.source.index("    def _show_images_page")
        end = self.source.index("    def _populate_image_repositories", start)
        page = self.source[start:end]
        for title in (
            "Repositorio e imagen",
            "Inspección y verificación",
            "Exploración y descarga",
            "Extracción de particiones",
            "Resultado y actividad",
        ):
            self.assertIn(f'title="{title}"', page)
            self.assertIn("Adw.PreferencesGroup(", page)
        self.assertIn("def add_image_row(", page)
        self.assertIn("row.add_suffix(widget)", page)
        self.assertIn("row.set_activatable_widget(widget)", page)
        for widget in (
            "self.image_repository", "self.image_select", "self.image_partition",
            "self.image_browse_path", "self.image_download_path", "self.image_cancel",
        ):
            self.assertIn(widget, page)
        for callback in (
            "self._inspect_selected_image", "self._verify_selected_image",
            "self._browse_selected_image", "self._download_selected_image_file",
            "self._extract_selected_partition", "self._cancel_image_extraction",
        ):
            self.assertIn(callback, page)
        for state in ('"images"', '"empty"', '"loading"', '"error"'):
            self.assertIn(state, page)
        self.assertIn('self.api.submit("remote_repositories"', page)

    def test_images_page_includes_verified_file_and_s3_repositories(self):
        self.assertIn('self.api.submit("remote_repositories",', self.source)
        self.assertIn("self._populate_image_repositories(result)", self.source)
        self.assertIn('self.api.submit("s3_repositories",', self.source)
        self.assertIn("self._populate_image_s3_repositories(result)", self.source)
        self.assertIn('item.get("mounted") and item.get("verified")', self.source)
        self.assertIn('"_repository_kind": "remote"', self.source)
        self.assertIn('"_repository_kind": "s3"', self.source)
        self.assertIn('if repository and repository.get("read_only")', self.source)
        self.assertIn('repository.get("_repository_kind") == "remote"', self.source)
        self.assertIn("if index > 0 and index - 1 < len(getattr(self, \"image_repositories\", [])):", self.source)
        self.assertIn('not repository.get("mounted") or not repository.get("verified")', self.source)

    def test_remote_job_definition_create_and_import_callbacks_are_page_scoped(self):
        create = ast.get_source_segment(self.source, self.methods["_create_remote_job"])
        imported = ast.get_source_segment(self.source, self.methods["_import_remote_job"])
        imported_done = ast.get_source_segment(self.source, self.methods["_remote_job_imported"])
        self.assertIn("page_generation = self._remote_jobs_page_generation", create)
        self.assertIn("_remote_job_action_done(", create)
        self.assertIn("page_generation = self._remote_jobs_page_generation", imported)
        self.assertIn("_remote_job_imported(result, generation)", imported)
        self.assertIn("self._remote_job_import_result = result", imported_done)
        self.assertIn("page_generation != self._remote_jobs_page_generation", imported_done)


    def test_remote_job_actions_are_bound_to_page_and_selected_job(self):
        context = ast.get_source_segment(self.source, self.methods["_remote_job_context_is_current"])
        stop = ast.get_source_segment(self.source, self.methods["_stop_remote_job_after_status"])
        submit = ast.get_source_segment(self.source, self.methods["_submit_remote_job_action"])
        done = ast.get_source_segment(self.source, self.methods["_remote_job_action_done"])
        failed = ast.get_source_segment(self.source, self.methods["_remote_job_action_failed"])
        self.assertIn("page_generation != self._remote_jobs_page_generation", context)
        self.assertIn('str(jobs[selected - 1].get("job_id") or "") == job_id', context)
        self.assertIn("_remote_job_context_is_current(page_generation, job_id)", stop)
        self.assertIn("self._submit_remote_job_action(\"stop_deployment_service\"", stop)
        self.assertIn("on_success=lambda result: self._remote_job_action_done", submit)
        self.assertIn("self._remote_job_action_results", done)
        self.assertIn("_remote_job_context_is_current(page_generation, job_id)", done)
        self.assertIn("_remote_job_context_is_current(page_generation, job_id)", failed)
        self.assertIn("self._remote_job_context_is_current(generation, job_id)", done)


    def test_server_and_pxe_action_callbacks_are_page_guarded(self):
        server_done = ast.get_source_segment(self.source, self.methods["_server_action_done"])
        server_failed = ast.get_source_segment(self.source, self.methods["_server_action_failed"])
        pxe_done = ast.get_source_segment(self.source, self.methods["_pxe_action_done"])
        pxe_failed = ast.get_source_segment(self.source, self.methods["_pxe_action_failed"])
        for callback in (server_done, server_failed, pxe_done, pxe_failed):
            self.assertIn("page_generation != self._server_status_page_generation", callback)
        self.assertIn("self._server_action_result = result", server_done)
        self.assertIn("self._server_action_results.append(result)", server_done)
        self.assertIn("self._pxe_action_result = result", pxe_done)
        self.assertIn("self._pxe_action_results.append(result)", pxe_done)
        for action in ("bootstrap_server", "renew_server_certificate", "rotate_server_keypair",
                       "start_pxe_services", "stop_pxe_services"):
            self.assertIn(f'"{action}"', self.source)
        self.assertIn("window_generation = self._server_window_page_generation", self.source)
        self.assertIn("window == self._page_generation", self.source)


    def test_network_actions_bind_both_navigation_and_request_generations(self):
        page = ast.get_source_segment(self.source, self.methods["_show_network_page"])
        apply = ast.get_source_segment(self.source, self.methods["_apply_network_profile"])
        applied = ast.get_source_segment(self.source, self.methods["_network_applied"])
        failed = ast.get_source_segment(self.source, self.methods["_network_failed"])
        self.assertIn("window_generation = self._page_generation", page)
        self.assertIn("window_generation == self._page_generation", page)
        self.assertIn("apply_generation = self._network_apply_generation", apply)
        self.assertIn("request == self._network_apply_generation", apply)
        self.assertIn("apply_generation != getattr(self, \"_network_apply_generation\", None)", applied)
        self.assertIn("window_generation != self._page_generation", failed)
        self.assertIn("current_window_generation = self._page_generation", applied)
        self.assertIn("current_window_generation == self._page_generation", applied)

    def test_tls_and_pxe_callbacks_capture_submission_context(self):
        server_page = ast.get_source_segment(self.source, self.methods["_show_server_status_page"])
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_server_status"])
        renew = ast.get_source_segment(self.source, self.methods["_renew_server_certificate"])
        rotate = ast.get_source_segment(self.source, self.methods["_rotate_server_keypair"])
        validate = ast.get_source_segment(self.source, self.methods["_validate_pxe_profile"])
        validated = ast.get_source_segment(self.source, self.methods["_pxe_profile_validated"])
        start = ast.get_source_segment(self.source, self.methods["_start_pxe_services"])
        stop = ast.get_source_segment(self.source, self.methods["_stop_pxe_services"])
        self.assertIn("self._server_window_page_generation = self._page_generation", server_page)
        self.assertIn("window_generation == self._page_generation", refresh)
        self.assertIn("window_generation = self._server_window_page_generation", renew)
        self.assertIn("window_generation = self._server_window_page_generation", rotate)
        self.assertIn("snapshot=dict(profile)", validate)
        self.assertIn("self._pxe_profile = profile", validated)
        self.assertIn("window_generation != self._page_generation", validated)
        self.assertIn("profile = dict(self._pxe_profile)", start)
        self.assertIn("window_generation = self._server_window_page_generation", stop)
        self.assertIn("self._pxe_action_done(result, page)", stop)
        self.assertIn("window_generation = self._server_window_page_generation", stop)

    def test_server_and_pxe_refresh_callbacks_reject_navigation_staleness(self):
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_server_status"])
        pxe_repositories = ast.get_source_segment(self.source, self.methods["_refresh_pxe_answer_repositories"])
        self.assertIn("window_generation == self._page_generation", refresh)
        self.assertIn("self._server_status_failed(error, generation)", refresh)
        self.assertIn("window_generation == self._page_generation", pxe_repositories)

    def test_pxe_answer_publish_and_revoke_callbacks_keep_job_identity(self):
        publish = ast.get_source_segment(self.source, self.methods["_publish_pxe_answer"])
        published = ast.get_source_segment(self.source, self.methods["_pxe_answer_published"])
        revoke = ast.get_source_segment(self.source, self.methods["_revoke_pxe_answer"])
        revoked = ast.get_source_segment(self.source, self.methods["_pxe_answer_revoked"])
        self.assertIn("request_generation = self._pxe_answer_action_generation", publish)
        self.assertIn("requested_job_id", published)
        self.assertIn('self._pxe_answer_action_results["publish:" + requested_job_id]', published)
        self.assertIn('{"job_id": job_id}', revoke)
        self.assertIn('self._pxe_answer_action_results["revoke:" + job_id]', revoked)
        self.assertIn('self.pxe_answer_revoke_id.get_text().strip() != job_id', revoked)

    def test_age_passphrase_status_and_secret_submission_are_page_scoped(self):
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_pxe_passphrase_status"])
        loaded = ast.get_source_segment(self.source, self.methods["_pxe_passphrase_status_loaded"])
        submit = ast.get_source_segment(self.source, self.methods["_submit_pxe_passphrase"])
        accepted = ast.get_source_segment(self.source, self.methods["_pxe_passphrase_submitted"])
        failed = ast.get_source_segment(self.source, self.methods["_pxe_passphrase_submit_failed"])
        self.assertIn("request_generation = self._pxe_passphrase_status_generation", refresh)
        self.assertIn("window_generation != self._page_generation", loaded)
        self.assertIn('{"passphrase": passphrase}', submit)
        self.assertIn("request_generation = self._pxe_passphrase_submit_generation", submit)
        self.assertIn("window_generation != self._page_generation", accepted)
        self.assertIn("self.pxe_passphrase.set_text(\"\")", accepted)
        self.assertIn("window_generation != self._page_generation", failed)

    def test_age_recipient_actions_use_server_page_callbacks(self):
        export = ast.get_source_segment(self.source, self.methods["_export_server_age_recipients"])
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_client_age_recipients"])
        self.assertIn("page_generation = self._server_status_page_generation", export)
        self.assertIn("self._server_action_done(result, page_generation)", export)
        self.assertIn("page_generation = self._server_status_page_generation", refresh)
        self.assertIn("self._server_action_done(result, page_generation)", refresh)

    def test_client_action_callbacks_preserve_results_and_reject_stale_views(self):
        start = self.source.index("    def _start_client_job")
        end = self.source.index("    def _show_client_job_rows", start)
        callbacks = self.source[start:end]
        self.assertIn("inspection_generation = self._client_inspection_generation", callbacks)
        self.assertIn("page_generation != self._client_page_generation", callbacks)
        self.assertIn("self._client_remote_job_results", callbacks)
        self.assertIn("status_generation != self._client_status_generation", callbacks)
        self.assertIn("current_job.get(\"job_id\")", callbacks)
        self.assertIn("on_success=lambda result: self._client_job_started", callbacks)
        self.assertIn("on_error=lambda error: self._client_job_failed", callbacks)


    def test_client_inventory_callbacks_reject_detached_page_results(self):
        page = ast.get_source_segment(self.source, self.methods["_show_client_jobs_page"])
        interfaces = ast.get_source_segment(self.source, self.methods["_populate_client_interfaces"])
        inventory = ast.get_source_segment(self.source, self.methods["_populate_client_inventory"])
        self.assertIn("window_generation = self._page_generation", page)
        self.assertIn("window_generation == self._page_generation", page)
        self.assertIn("window_generation != self._page_generation", interfaces)
        self.assertIn("window_generation != self._page_generation", inventory)

    def test_pxe_repository_callbacks_reject_detached_page_results(self):
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_pxe_answer_repositories"])
        s3 = ast.get_source_segment(self.source, self.methods["_pxe_answer_s3_repositories"])
        remote = ast.get_source_segment(self.source, self.methods["_pxe_answer_remote_repositories"])
        error = ast.get_source_segment(self.source, self.methods["_pxe_answer_repository_error"])
        self.assertIn("window_generation == self._page_generation", refresh)
        self.assertIn("window_generation != self._page_generation", s3)
        self.assertIn("window_generation != self._page_generation", remote)
        self.assertIn("window_generation != self._page_generation", error)

    def test_client_job_history_refresh_rejects_older_responses(self):
        page = ast.get_source_segment(self.source, self.methods["_show_client_jobs_page"])
        refresh = ast.get_source_segment(self.source, self.methods["_refresh_client_job_history"])
        self.assertIn('refresh.connect("clicked", self._refresh_client_job_history)', page)
        self.assertIn("self._refresh_client_job_history()", page)
        self.assertIn("self._client_history_generation", refresh)
        self.assertIn("request_generation == self._client_history_generation", refresh)
        self.assertIn("page_generation == self._client_page_generation", refresh)
        self.assertIn('"deployment_jobs"', refresh)

    def test_client_job_controls_use_semantic_libadwaita_groups(self):
        start = self.source.index("    def _show_client_jobs_page")
        end = self.source.index("    def _show_client_job_rows", start)
        page = self.source[start:end]
        for title in (
            "Conexión e inspección autenticada",
            "Destino local",
            "Transferencia y protección",
            "Ejecución y seguimiento",
        ):
            self.assertIn(f'title="{title}"', page)
        for widget in (
            "self.client_server_host", "self.client_job_id", "self.client_interface",
            "self.client_target", "self.client_compression", "self.client_encrypt",
            "self.client_igmp", "self.client_confirmation",
        ):
            self.assertIn(f"row.add_suffix({widget})", page)
        for callback in (
            "self._inspect_client_job", "self._start_client_job",
            "self._refresh_client_job_status", "self._update_client_confirmation",
        ):
            self.assertIn(callback, page)
        self.assertIn('self.client_confirmation.set_placeholder_text("Escribe exactamente ERASE destino o READ destino TO identidad")', page)
        self.assertIn('self.api.submit("network_interfaces"', page)
        self.assertIn('self.api.submit("inventory"', page)


    def test_raw_disk_capture_supports_one_shot_age_passphrase_delivery(self):
        self.assertIn("self.capture_passphrase = Gtk.PasswordEntry()", self.source)
        self.assertIn('"provide_capture_passphrase"', self.source)
        self.assertIn('"encrypt_passphrase": True', self.source)
        self.assertIn("self.capture_passphrase.set_text(\"\")", self.source)
        self.assertIn("self._capture_passphrase_failed", self.source)

    def test_capture_failure_is_page_and_request_scoped(self):
        start = self.source.index("    def _capture_failed")
        end = self.source.index("    def _refresh_status", start)
        callback = self.source[start:end]
        self.assertIn("self._capture_action_errors[key] = str(error)", callback)
        self.assertIn("page_generation != self._page_generation", self.source)
        self.assertIn("request_generation != getattr(self, \"_capture_request_generation\", None)", callback)
        self.assertIn('self.capture_passphrase.set_text("")', callback)
        self.assertIn("self.capture_cancel.set_sensitive(False)", callback)

    def test_local_operation_callbacks_keep_identity_and_secret_per_request(self):
        submit = self.source[self.source.index("    def _submit_capture_operation"):self.source.index("    def _capture_view_is_current")]
        accepted = self.source[self.source.index("    def _capture_accepted"):self.source.index("    def _capture_passphrase_delivered")]
        poll = ast.get_source_segment(self.source, self.methods["_poll_capture_status"])
        status = ast.get_source_segment(self.source, self.methods["_show_capture_status"])
        page = self.source[self.source.index('elif page_id == "operations":'):self.source.index('        else:\n            self.page_description.set_text("Esta pantalla aún no se ha migrado', self.source.index('elif page_id == "operations":'))]
        self.assertIn('"passphrase": passphrase', submit)
        self.assertIn("request_generation", submit)
        self.assertIn("page_generation", submit)
        self.assertIn('self._local_operation_results[operation_id]', accepted)
        self.assertIn('"passphrase": passphrase', accepted)
        self.assertIn("lambda status: self._show_capture_status(status, operation_id, page_generation)", poll)
        self.assertIn("self._capture_view_is_current(page_generation, operation_id)", status)
        self.assertIn("self._poll_capture_status(active_operation_id, operations_page_generation)", page)

    def test_p2v_and_image_status_reject_mismatched_operation_ids_and_retry(self):
        p2v = ast.get_source_segment(self.source, self.methods["_p2v_operation_status_loaded"])
        image = ast.get_source_segment(self.source, self.methods["_show_image_extraction_status"])
        for callback, poller in ((p2v, "_poll_p2v_operation"), (image, "_poll_image_extraction")):
            self.assertIn('status.get("operation_id") not in (None, operation_id)', callback)
            self.assertIn("se reintentará", callback)
            self.assertIn(poller, callback)

    def test_local_operation_status_polling_is_bound_to_operation_id(self):
        status = ast.get_source_segment(self.source, self.methods["_show_capture_status"])
        failed = ast.get_source_segment(self.source, self.methods["_capture_status_failed"])
        cancel = ast.get_source_segment(self.source, self.methods["_cancel_disk_capture"])
        self.assertIn('{"operation_id": operation_id}', self.source[self.source.index('    def _poll_capture_status'):self.source.index('    def _show_capture_status')])
        self.assertIn("lambda: self._poll_capture_status(operation_id, page_generation)", status)
        self.assertIn("lambda: self._poll_capture_status(operation_id, page_generation)", failed)
        self.assertIn('"operation_id": operation_id', cancel)
        self.assertIn("operation_id=operation_id", cancel)


    def test_restore_profiles_use_libadwaita_preference_groups(self):
        start = self.source.index("    def _show_restore_profiles_page")
        end = self.source.index("    def _populate_profile_inventory", start)
        page = self.source[start:end]
        self.assertEqual(page.count("Adw.PreferencesGroup("), 3)
        self.assertIn('title="Origen y destino"', page)
        self.assertIn('title="Definición del perfil"', page)
        self.assertIn('title="Ejecución controlada"', page)
        self.assertIn("row.add_suffix(widget)", page)
        self.assertIn("row.set_activatable_widget(widget)", page)
        self.assertIn('self.profile_confirmation.set_placeholder_text("ERASE /dev/…")', page)
        self.assertIn("self.profile_cancel.set_sensitive(False)", page)
        self.assertIn('self.api.submit("inventory"', page)
        self.assertIn('self.api.submit("remote_repositories"', page)


    def test_operation_log_uses_libadwaita_preference_groups(self):
        start = self.source.index("    def _show_operation_log_page")
        end = self.source.index("    def _show_recovery_jobs_page", start)
        page = self.source[start:end]
        self.assertEqual(page.count("Adw.PreferencesGroup("), 3)
        self.assertIn('title="Estado del registro"', page)
        self.assertIn('title="Cancelación controlada"', page)
        self.assertIn('title="Operaciones registradas"', page)
        self.assertIn("row.set_activatable_widget(self.operation_select)", page)
        self.assertIn("row.set_activatable_widget(cancel)", page)
        self.assertIn('self.operation_confirmation.set_placeholder_text("CANCEL <operation_id>")', page)
        self.assertIn('title="Sin operaciones registradas"', page)
        self.assertIn("self._refresh_operation_log(None)", page)

    def test_restore_profile_callbacks_are_page_and_request_scoped(self):
        page = self.source[self.source.index("    def _show_restore_profiles_page"):self.source.index("    def _populate_profile_inventory")]
        load = ast.get_source_segment(self.source, self.methods["_load_restore_profiles_for_repository"])
        create = ast.get_source_segment(self.source, self.methods["_create_restore_profile"])
        accepted = ast.get_source_segment(self.source, self.methods["_restore_profile_operation_accepted"])
        failed = ast.get_source_segment(self.source, self.methods["_profile_failed"])
        self.assertIn("self._profile_page_generation = self._page_generation", page)
        self.assertIn("page_generation == self._page_generation", page)
        self.assertIn("page_generation == self._page_generation and generation == self._profile_repository_generation", load)
        self.assertIn("request_generation", create)
        self.assertIn('request_kind="create"', create)
        execute = self.source[self.source.index("    def _execute_selected_restore_profile"):self.source.index("    def _restore_profile_operation_accepted")]
        self.assertIn('request_kind="execute"', execute)
        self.assertIn('request_kind == "create"', failed)
        self.assertIn("request_is_current", accepted)
        self.assertIn("self._latest_profile_operation_id = operation_id", accepted)
        self.assertIn("page_generation != self._page_generation", failed)

    def test_restore_profile_status_polling_keeps_operation_identity(self):
        poll = ast.get_source_segment(self.source, self.methods["_poll_restore_profile_operation"])
        status = ast.get_source_segment(self.source, self.methods["_show_restore_profile_operation_status"])
        page = self.source[self.source.index("    def _show_restore_profiles_page"):self.source.index("    def _populate_profile_inventory")]
        self.assertIn('{"operation_id": operation_id}', poll)
        self.assertIn("_show_restore_profile_operation_status(status, operation_id, page_generation)", poll)
        self.assertIn("operation_id != getattr(self, \"profile_operation_id\", None)", status)
        self.assertIn("_poll_restore_profile_operation(pending_operation_id, page_generation)", page)
        self.assertIn('self._profile_operation_results.setdefault(operation_id, {})["status"] = status', status)

    def test_operation_log_cancel_feedback_is_scoped_to_selected_operation(self):
        cancel = ast.get_source_segment(self.source, self.methods["_cancel_selected_logged_operation"])
        done = ast.get_source_segment(self.source, self.methods["_operation_cancelled"])
        failed = ast.get_source_segment(self.source, self.methods["_operation_log_failed"])
        self.assertIn("page_generation = self._operation_log_page_generation", cancel)
        self.assertIn("_operation_cancelled(result, operation_id, page_generation)", cancel)
        self.assertIn("selected_id != operation_id", done)
        self.assertIn("page_generation != self._page_generation", done)
        self.assertIn("self._operation_log_errors[operation_id] = str(error)", failed)

    def test_recovery_jobs_use_libadwaita_preference_groups(self):
        start = self.source.index("    def _show_recovery_jobs_page")
        end = self.source.index("    def _refresh_recovery_jobs", start)
        page = self.source[start:end]
        self.assertEqual(page.count("Adw.PreferencesGroup("), 2)
        self.assertIn('title="Estado de recuperación"', page)
        self.assertIn('title="Trabajos ddrescue"', page)
        self.assertIn('title="Sin trabajos de recuperación"', page)
        self.assertIn("row.set_activatable_widget(refresh)", page)
        self.assertIn("self._refresh_recovery_jobs(None)", page)

    def test_raw_disk_capture_preserves_exclusive_age_encryption_modes(self):
        page = self.source[self.source.index('elif page_id == "operations":'):self.source.index('        else:\n            self.page_description.set_text("Esta pantalla aún no se ha migrado', self.source.index('elif page_id == "operations":'))]
        start = ast.get_source_segment(self.source, self.methods["_start_disk_capture"])
        mode = ast.get_source_segment(self.source, self.methods["_capture_mode_changed"])
        toggle = ast.get_source_segment(self.source, self.methods["_capture_encryption_changed"])
        self.assertIn('Gtk.CheckButton(label="Cifrar con destinatarios age")', page)
        self.assertIn('Gtk.CheckButton(label="Cifrar con frase secreta de un solo uso")', page)
        self.assertIn('self.capture_encrypt.connect("toggled", self._capture_encryption_changed)', page)
        self.assertIn('self.capture_passphrase_toggle.connect("toggled", self._capture_encryption_changed)', page)
        self.assertIn("self.capture_passphrase_toggle.set_active(False)", toggle)
        self.assertIn("self.capture_encrypt.set_active(False)", toggle)
        self.assertIn("recipient_encryption_visible = kind in {0, 1, 2, 3, 4}", mode)
        self.assertIn("passphrase_encryption_visible = kind == 0", mode)
        self.assertIn('"encrypt": (self.capture_encrypt.get_active() or passphrase_encryption) and not qcow2', start)
        self.assertIn('if kind == 0 and not qcow2 and self.capture_passphrase_toggle.get_active():', start)
        self.assertIn('params["encrypt_passphrase"] = True', start)
        self.assertIn("capture_passphrase = self.capture_passphrase.get_text()", start)



    def test_server_and_pxe_action_callbacks_use_captured_window_generation(self):
        server_done = ast.get_source_segment(self.source, self.methods["_server_action_done"])
        server_failed = ast.get_source_segment(self.source, self.methods["_server_action_failed"])
        pxe_done = ast.get_source_segment(self.source, self.methods["_pxe_action_done"])
        pxe_failed = ast.get_source_segment(self.source, self.methods["_pxe_action_failed"])
        self.assertIn("window_generation != self._page_generation", server_done)
        self.assertIn("window_generation != self._page_generation", server_failed)
        self.assertIn("window_generation != self._page_generation", pxe_done)
        self.assertIn("window_generation != self._page_generation", pxe_failed)
        for action in ("_bootstrap_server", "_renew_server_certificate", "_rotate_server_keypair",
                       "_export_server_age_recipients", "_refresh_client_age_recipients"):
            method = ast.get_source_segment(self.source, self.methods[action])
            self.assertIn("window_generation = self._server_window_page_generation", method)
            self.assertIn("window=window_generation", method)
            self.assertIn("_server_action_done(result, page, window)", method)
            self.assertIn("_server_action_failed(error, page, window)", method)
        start = ast.get_source_segment(self.source, self.methods["_start_pxe_services"])
        stop = ast.get_source_segment(self.source, self.methods["_stop_pxe_services"])
        self.assertIn("window=window_generation", start)
        self.assertIn("window=window_generation", stop)


if __name__ == "__main__":
    unittest.main()
