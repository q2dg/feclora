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
        self.assertIn('self.image_session_id = result.get("session_id", "")', self.source)

    def test_proportional_restore_requires_smaller_target_and_kernel_identities(self):
        self.assertIn('"Restauración proporcional a disco menor"', self.source)
        self.assertIn('"restore_proportional_disk"', self.source)
        self.assertIn('source_device.get("major_minor")', self.source)
        self.assertIn('target_device.get("major_minor")', self.source)
        self.assertIn('target_device["size_bytes"] >= source_device["size_bytes"]', self.source)

    def test_system_and_server_pages_render_service_certificate_and_pxe_status(self):
        self.assertIn('self.api.submit("pxe_service_status"', self.source)
        self.assertIn('self.api.submit("network_interfaces"', self.source)
        self.assertIn('status.get("certificate_status")', self.source)
        self.assertIn('def _show_system_page', self.source)
        self.assertIn('def _show_server_status_page', self.source)

    def test_repository_page_lists_remote_and_s3_storage_state(self):
        self.assertIn('self.api.submit("remote_repositories"', self.source)
        self.assertIn('self.api.submit("s3_repositories"', self.source)
        self.assertIn('item.get("mounted")', self.source)
        self.assertIn('item.get("verified")', self.source)
        self.assertIn('item.get("read_only")', self.source)

    def test_remote_deployment_and_client_history_pages_use_persistent_api(self):
        for action in ('self.api.submit(action, on_success=lambda response: self._show_history_rows', 'self.api.submit("deployment_jobs"', 'self._history_page("Historial de despliegues', 'self._history_page("Trabajos remotos'):
            self.assertIn(action, self.source)
        self.assertIn('"journals", "journals"', self.source)
        self.assertIn('details.get("state")', self.source)

    def test_operation_log_and_ddrescue_history_use_persistent_api_records(self):
        self.assertIn('self.api.submit("local_operations"', self.source)
        self.assertIn('self.api.submit("cancel_local_operation"', self.source)
        self.assertIn('operation_confirmation.get_text() != expected', self.source)
        self.assertIn('self.api.submit("recovery_jobs"', self.source)
        self.assertIn('details.get("destination_may_be_partial")', self.source)
        self.assertIn('item.get("unresolved_bytes")', self.source)
        self.assertIn('item.get("progress_percent")', self.source)

    def test_network_page_uses_active_profiles_and_validated_ipv4_checkpoint(self):
        for action in ('self.api.submit("network_connection_profiles"', 'self.api.submit("network_interfaces"', 'self.api.submit("apply_network_profile"'):
            self.assertIn(action, self.source)
        self.assertIn('ipaddress.IPv4Address(self.network_address.get_text().strip())', self.source)
        self.assertIn('"rollback_timeout": 120', self.source)
        self.assertIn('interface.get("interface") != profile.get("device")', self.source)

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
        self.assertIn('self.api.submit("import_p2v"', self.source)
        self.assertIn('self.api.submit("export_p2v_s3"', self.source)
        self.assertIn('"source_image_id": source_image_id', self.source)
        self.assertIn('"source_repository_id": sources[source_index - 1]["id"]', self.source)
        self.assertIn('params["destination_repository_id"]', self.source)
        self.assertIn('self.p2v_import_repository', self.source)
        self.assertIn('self.p2v_export_repository', self.source)
        self.assertIn('self.p2v_result.set_text', self.source)

    def test_repository_management_and_credential_controls_use_allowlisted_api(self):
        for action in (
            '"check": "check_s3_repository"',
            '"remove": "remove_s3_repository"',
            '"check": "check_remote_repository"',
            '"mount": "mount_remote_repository"',
            '"unmount": "unmount_remote_repository"',
            '"remove": "remove_remote_repository"',
            'self.api.submit("systemd_credentials"',
            'self.api.submit("put_systemd_credential"',
            'self.api.submit("remove_systemd_credential"',
        ):
            self.assertIn(action, self.source)
        self.assertIn('mount_state != "unmounted"', self.source)
        self.assertIn('mount_state != "identity_verified"', self.source)
        self.assertIn('f"REMOVE {identifier}"', self.source)
        self.assertIn('credential_management', self.source)
        self.assertIn('repository_management_rows', self.source)
        self.assertIn('f"Definición {provider} cargada; guarda los cambios en el formulario."', self.source)
        self.assertIn('Definición S3 cargada', self.source)
        self.assertIn('action = "update_remote_repository" if existing else "add_remote_repository"', self.source)
        self.assertIn('action = "update_s3_repository" if existing else "add_s3_repository"', self.source)
        self.assertIn('self.api.submit(api_action', self.source)
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
        self.assertIn('self._pxe_pending_profile = profile', self.source)
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

    def test_network_configuration_uses_libadwaita_preferences_rows(self):
        self.assertIn('Adw.PreferencesGroup(\n            title="Conexión IPv4"', self.source)
        self.assertIn("row = Adw.ActionRow(title=title)", self.source)
        self.assertIn("row.add_suffix(widget)", self.source)
        self.assertIn("row.set_activatable_widget(widget)", self.source)
        self.assertIn('add_network_row("Método IPv4", self.network_method)', self.source)
        self.assertIn('add_network_row("DNS IPv4 separados por comas", self.network_dns)', self.source)
        self.assertIn("self._network_method_changed(self.network_method, None)", self.source)
        self.assertIn("self.network_address_row = add_network_row", self.source)
        self.assertIn("self.network_dns_row = add_network_row", self.source)
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


if __name__ == "__main__":
    unittest.main()

    def test_raw_disk_capture_supports_one_shot_age_passphrase_delivery(self):
        self.assertIn("self.capture_passphrase = Gtk.PasswordEntry()", self.source)
        self.assertIn('"provide_capture_passphrase"', self.source)
        self.assertIn('"encrypt_passphrase": True', self.source)
        self.assertIn("self.capture_passphrase.set_text(\"\")", self.source)
        self.assertIn("self._capture_passphrase_failed", self.source)

    def test_capture_failure_clears_pending_age_passphrase(self):
        start = self.source.index("    def _capture_failed")
        end = self.source.index("    def _refresh_status", start)
        callback = self.source[start:end]
        self.assertIn("self.active_capture_passphrase = \"\"", callback)
        self.assertIn("self.capture_passphrase.set_text(\"\" )".replace(" ", ""), callback.replace(" ", ""))
        self.assertIn("self.capture_cancel.set_sensitive(False)", callback)
