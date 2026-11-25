"""GTK4 frontend prototype for the native Wayland Feclora kiosk.

This frontend is not the production boot entry point until every operator
workflow has been migrated and accepted. The existing Textual service remains
enabled during the staged migration.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path
from typing import Any

# Fail closed: GDK must use the native Wayland backend only.
os.environ["GDK_BACKEND"] = "wayland"
os.environ.pop("DISPLAY", None)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib

from feclora.gtk_api import GtkAPIClient
from feclora.ui_catalog import KEYBOARD_LAYOUTS, LANGUAGES, MESSAGES, PAGES, PAGE_MESSAGE_KEYS


class FecloraGTK:
    def __init__(self, application: Adw.Application) -> None:
        self.application = application
        self.language = self._load_language()
        self.keyboard_layout = "us"
        self.keyboard_selection = "us"
        self.api = GtkAPIClient()
        self.window = Adw.ApplicationWindow(application=application)
        self.toast_overlay = Adw.ToastOverlay()
        self.window.set_content(self.toast_overlay)
        self.window.set_title("Feclora")
        self.window.set_decorated(False)
        self.window.set_deletable(False)
        self.window.fullscreen()
        self.window.connect("close-request", self._on_close_request)
        self._show_welcome()
        GLib.idle_add(self._report_boot_rendered)
        self.api.submit("get_keyboard_layout", on_success=self._accept_keyboard_layout, on_error=self._show_error)

    @staticmethod
    def _language_path() -> Path:
        return Path(os.environ.get("HOME", str(Path.home()))) / ".config/feclora/language"

    @classmethod
    def _load_language(cls) -> str:
        try:
            code = cls._language_path().read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return "es"
        return code if code in MESSAGES else "es"

    @classmethod
    def _save_language(cls, code: str) -> None:
        if code not in MESSAGES:
            raise ValueError("unsupported interface language")
        path = cls._language_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(code + "\n", encoding="utf-8")
        path.chmod(0o600)

    def tr(self, key: str) -> str:
        return MESSAGES.get(self.language, MESSAGES["es"]).get(key, MESSAGES["es"].get(key, key))

    @staticmethod
    def _on_close_request(_window: Gtk.Window) -> bool:
        return True

    def _report_boot_rendered(self) -> bool:
        if Path("/dev/virtio-ports/org.feclora.boot-smoke").exists():
            ready = Path("/run/feclora-gui/ready")
            ready.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            ready.write_text("rendered\n", encoding="ascii")
        return GLib.SOURCE_REMOVE

    def _show_error(self, error: Exception) -> None:
        message = f"{self.tr('apply_error')} {error}"
        if hasattr(self, "status"):
            self.status.set_text(message)
        if hasattr(self, "status_summary"):
            self.status_summary.set_text(message)
        if hasattr(self, "inventory_summary"):
            self.inventory_summary.set_text(message)
        if hasattr(self, "toast_overlay"):
            self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _accept_keyboard_layout(self, result: dict[str, Any]) -> None:
        layout = result.get("layout")
        values = [value for _label, value in KEYBOARD_LAYOUTS]
        if layout in values:
            self.keyboard_layout = layout
            self.keyboard_selection = layout
            if hasattr(self, "keyboard_dropdown"):
                self.keyboard_dropdown.set_selected(values.index(layout))

    @staticmethod
    def _box(orientation: Gtk.Orientation, spacing: int = 12) -> Gtk.Box:
        return Gtk.Box(orientation=orientation, spacing=spacing)

    def _present_content(self, content: Gtk.Widget, title: str, subtitle: str = "") -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title, subtitle)
        header.set_title_widget(self.window_title)
        self.back_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.back_button.set_tooltip_text("Volver a la navegación")
        self.back_button.connect("clicked", self._show_navigation_sidebar)
        header.pack_start(self.back_button)
        self.back_button.set_visible(False)
        toolbar.add_top_bar(header)
        toolbar.set_content(content)
        self.toast_overlay.set_child(toolbar)

    def _show_navigation_sidebar(self, _button: Gtk.Button) -> None:
        if hasattr(self, "navigation_split"):
            self.navigation_split.set_show_content(False)

    def _navigation_split_collapsed(self, split: Adw.NavigationSplitView, _param: Any) -> None:
        if hasattr(self, "back_button"):
            self.back_button.set_visible(split.get_collapsed())

    def _show_welcome(self) -> None:
        self._welcome_generation = getattr(self, "_welcome_generation", 0) + 1
        root = self._box(Gtk.Orientation.VERTICAL, 18)
        root.set_halign(Gtk.Align.CENTER)
        root.set_valign(Gtk.Align.CENTER)
        root.set_margin_top(32)
        root.set_margin_bottom(32)
        root.set_margin_start(24)
        root.set_margin_end(24)

        title = Gtk.Label(label=self.tr("first_title"))
        title.add_css_class("title-1")
        root.append(title)
        tagline = Gtk.Label(label=self.tr("tagline"))
        tagline.set_wrap(True)
        tagline.set_justify(Gtk.Justification.CENTER)
        root.append(tagline)

        language_group = Adw.PreferencesGroup(title="Idioma de la interfaz", description="Selecciona el idioma que utilizará Feclora.")
        root.append(language_group)
        self.language_dropdown = Gtk.DropDown.new_from_strings([label for label, _code in LANGUAGES])
        self.language_dropdown.set_selected(next((i for i, (_label, code) in enumerate(LANGUAGES) if code == self.language), 1))
        self.language_dropdown.set_valign(Gtk.Align.CENTER)
        self.language_dropdown.connect("notify::selected", self._language_changed)
        language_row = Adw.ActionRow(title=self.tr("language"))
        language_row.add_suffix(self.language_dropdown)
        language_row.set_activatable_widget(self.language_dropdown)
        language_group.add(language_row)

        keyboard_group = Adw.PreferencesGroup(title="Distribución del teclado", description="La distribución se aplica al sistema mediante la API local.")
        root.append(keyboard_group)
        self.keyboard_dropdown = Gtk.DropDown.new_from_strings([label for label, _value in KEYBOARD_LAYOUTS])
        keyboard_values = [value for _label, value in KEYBOARD_LAYOUTS]
        self.keyboard_dropdown.set_selected(keyboard_values.index(self.keyboard_selection) if self.keyboard_selection in keyboard_values else 0)
        self.keyboard_dropdown.set_valign(Gtk.Align.CENTER)
        keyboard_row = Adw.ActionRow(title=self.tr("keyboard"))
        keyboard_row.add_suffix(self.keyboard_dropdown)
        keyboard_row.set_activatable_widget(self.keyboard_dropdown)
        keyboard_group.add(keyboard_row)

        self.status = Gtk.Label(label=self.tr("language_scope"), xalign=0)
        self.status.set_wrap(True)
        self.status.set_selectable(True)
        status_row = Adw.ActionRow(title="Estado de configuración")
        status_row.add_suffix(self.status)
        keyboard_group.add(status_row)

        actions_group = Adw.PreferencesGroup(title="Acciones")
        root.append(actions_group)
        apply_button = Gtk.Button(label=self.tr("apply_keyboard"))
        apply_button.connect("clicked", self._apply_keyboard)
        apply_row = Adw.ActionRow(title="Aplicar distribución seleccionada")
        apply_row.add_suffix(apply_button)
        apply_row.set_activatable_widget(apply_button)
        actions_group.add(apply_row)
        continue_button = Gtk.Button(label=self.tr("continue"))
        continue_button.add_css_class("suggested-action")
        continue_button.connect("clicked", self._continue)
        continue_row = Adw.ActionRow(title="Guardar preferencias y continuar")
        continue_row.add_suffix(continue_button)
        continue_row.set_activatable_widget(continue_button)
        actions_group.add(continue_row)
        terminal_button = Gtk.Button(label=self.tr("terminal"))
        terminal_button.connect("clicked", self._open_root_terminal)
        terminal_row = Adw.ActionRow(title="Mantenimiento")
        terminal_row.add_suffix(terminal_button)
        terminal_row.set_activatable_widget(terminal_button)
        actions_group.add(terminal_row)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        clamp.set_child(root)
        self._present_content(clamp, "Feclora", self.tr("first_title"))
        self.window.present()
    def _language_changed(self, dropdown: Gtk.DropDown, _param: Any) -> None:
        index = dropdown.get_selected()
        if index < len(LANGUAGES):
            if hasattr(self, "keyboard_dropdown"):
                keyboard_index = self.keyboard_dropdown.get_selected()
                if keyboard_index < len(KEYBOARD_LAYOUTS):
                    self.keyboard_selection = KEYBOARD_LAYOUTS[keyboard_index][1]
            self.language = LANGUAGES[index][1]
            self._show_welcome()

    def _apply_keyboard(self, _button: Gtk.Button) -> None:
        index = self.keyboard_dropdown.get_selected()
        layout = KEYBOARD_LAYOUTS[index][1] if index < len(KEYBOARD_LAYOUTS) else "us"
        self.status.set_text("Aplicando distribución del teclado…")
        welcome_generation = self._welcome_generation
        self.api.submit(
            "set_keyboard_layout", {"layout": layout},
            on_success=lambda _result: self._keyboard_layout_applied(layout, welcome_generation),
            on_error=self._show_error,
        )

    def _keyboard_layout_applied(self, layout: str, welcome_generation: int | None = None) -> None:
        self.keyboard_layout = layout
        self.keyboard_selection = layout
        if welcome_generation is None or welcome_generation != self._welcome_generation:
            return
        self.status.set_text(self.tr("apply_ok"))

    def _open_root_terminal(self, _button: Gtk.Button) -> None:
        self.api.submit(
            "open_root_terminal",
            on_success=lambda _result: self.toast_overlay.add_toast(
                Adw.Toast.new("Solicitud de terminal root enviada.")
            ),
            on_error=self._show_error,
        )

    def _continue(self, _button: Gtk.Button) -> None:
        try:
            self._save_language(self.language)
        except OSError as exc:
            self.status.set_text(f"No se pudo guardar el idioma: {exc}")
            return
        self._welcome_generation = getattr(self, "_welcome_generation", 0) + 1
        self._show_navigation()

    def _show_navigation(self) -> None:
        sidebar = self._box(Gtk.Orientation.VERTICAL, 8)
        sidebar.add_css_class("navigation-sidebar")
        sidebar.set_size_request(280, -1)
        sidebar.set_margin_top(24)
        sidebar.set_margin_start(12)
        sidebar.set_margin_end(12)
        brand = Gtk.Label(label="FECLORA")
        brand.add_css_class("title-2")
        sidebar.append(brand)

        content = self._box(Gtk.Orientation.VERTICAL, 16)
        content.set_hexpand(True)
        content.set_margin_top(32)
        content.set_margin_start(32)
        content.set_margin_end(32)
        self.page_title = Gtk.Label(label=self.tr("overview"), xalign=0)
        self.page_title.add_css_class("title-1")
        content.append(self.page_title)
        self.page_description = Gtk.Label(label="", xalign=0)
        self.page_description.set_wrap(True)
        content.append(self.page_description)
        self.page_body = self._box(Gtk.Orientation.VERTICAL, 10)
        self.page_body.set_vexpand(True)
        page_scroller = Gtk.ScrolledWindow()
        page_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page_scroller.set_vexpand(True)
        page_scroller.set_child(self.page_body)
        content.append(page_scroller)

        navigation_group = Adw.PreferencesGroup(title="Secciones")
        sidebar.append(navigation_group)
        self.navigation_rows: dict[str, Adw.ActionRow] = {}
        self.navigation_icons: dict[str, Gtk.Image] = {}
        for page_id, _label in PAGES:
            row = Adw.ActionRow(title=self.tr(PAGE_MESSAGE_KEYS[page_id]))
            icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
            row.add_prefix(icon)
            row.set_activatable(True)
            row.add_css_class("navigation-row")
            row.connect("activated", self._select_page, page_id)
            navigation_group.add(row)
            self.navigation_rows[page_id] = row
            self.navigation_icons[page_id] = icon

        sidebar_scroller = Gtk.ScrolledWindow()
        sidebar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroller.set_child(sidebar)
        self.navigation_split = Adw.NavigationSplitView()
        self.navigation_split.set_sidebar(Adw.NavigationPage.new(sidebar_scroller, "Feclora"))
        self.navigation_split.set_content(Adw.NavigationPage.new(content, self.tr("overview")))
        self.navigation_split.set_min_sidebar_width(220)
        self.navigation_split.set_max_sidebar_width(320)
        self.navigation_split.set_sidebar_width_fraction(0.25)
        self.navigation_split.set_vexpand(True)
        self.navigation_split.connect("notify::collapsed", self._navigation_split_collapsed)
        self._present_content(self.navigation_split, "Feclora", self.tr("overview"))
        self._navigation_split_collapsed(self.navigation_split, None)
        self._select_page(None, "overview")

    def _clear_page(self) -> None:
        child = self.page_body.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.page_body.remove(child)
            child = following

    def _select_page(self, _row: Gtk.Widget | None, page_id: str) -> None:
        self._page_generation = getattr(self, "_page_generation", 0) + 1
        for navigation_id, row in self.navigation_rows.items():
            selected = navigation_id == page_id
            row.set_subtitle("Página actual" if selected else "")
            icon = self.navigation_icons[navigation_id]
            icon.set_from_icon_name("emblem-ok-symbolic" if selected else "go-next-symbolic")
        self._clear_page()
        page_title = self.tr(PAGE_MESSAGE_KEYS[page_id])
        self.page_title.set_text(page_title)
        if hasattr(self, "window_title"):
            self.window_title.set_title(page_title)
        if hasattr(self, "navigation_split") and self.navigation_split.get_collapsed():
            self.navigation_split.set_show_content(True)
        if hasattr(self, "navigation_split"):
            content_page = self.navigation_split.get_content()
            if content_page is not None:
                content_page.set_title(page_title)
        if page_id == "overview":
            self.page_description.set_text("Estado del equipo, configuración de roles y servicios locales.")

            def overview_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget, subtitle: str = "") -> Adw.ActionRow:
                row = Adw.ActionRow(title=title, subtitle=subtitle)
                row.add_suffix(widget)
                group.add(row)
                return row

            identity_group = Adw.PreferencesGroup(
                title="Identidad del equipo",
                description="Nombre del host y plataforma detectada.",
            )
            self.page_body.append(identity_group)
            self.status_summary = Gtk.Label(label="Consultando el estado del sistema…", xalign=0)
            self.status_summary.set_wrap(True)
            self.status_summary.set_selectable(True)
            overview_row(identity_group, "Host y plataforma", self.status_summary)

            configuration_group = Adw.PreferencesGroup(
                title="Configuración de Feclora",
                description="Disponibilidad de los roles de servidor y cliente.",
            )
            self.page_body.append(configuration_group)
            self.overview_configuration = Gtk.Label(label="Consultando configuración…", xalign=0)
            self.overview_configuration.set_wrap(True)
            self.overview_configuration.set_selectable(True)
            overview_row(configuration_group, "Roles configurados", self.overview_configuration)

            services_group = Adw.PreferencesGroup(
                title="Servicios del sistema",
                description="Estado comunicado por la API local.",
            )
            self.page_body.append(services_group)
            self.overview_services = Gtk.Label(label="Consultando servicios…", xalign=0)
            self.overview_services.set_wrap(True)
            self.overview_services.set_selectable(True)
            overview_row(services_group, "Servicios", self.overview_services)

            actions_group = Adw.PreferencesGroup(title="Acciones")
            self.page_body.append(actions_group)
            refresh = Gtk.Button(label="Actualizar estado")
            refresh_row = overview_row(actions_group, "Consulta del estado local", refresh)
            refresh_row.set_activatable_widget(refresh)
            refresh.connect("clicked", self._refresh_status)
            self._refresh_status(None)
        elif page_id == "inventory":
            self.page_description.set_text("Inventario jerárquico de dispositivos, particiones y volúmenes detectados.")

            status_group = Adw.PreferencesGroup(title="Estado del inventario")
            self.page_body.append(status_group)
            self.inventory_summary = Gtk.Label(label="Leyendo inventario…", xalign=0)
            self.inventory_summary.set_wrap(True)
            self.inventory_summary.set_selectable(True)
            status_row = Adw.ActionRow(title="Dispositivos detectados")
            status_row.add_suffix(self.inventory_summary)
            status_group.add(status_row)

            actions_group = Adw.PreferencesGroup(title="Acciones")
            self.page_body.append(actions_group)
            refresh = Gtk.Button(label="Actualizar inventario")
            refresh_row = Adw.ActionRow(title="Detección de almacenamiento")
            refresh_row.add_suffix(refresh)
            refresh_row.set_activatable_widget(refresh)
            actions_group.add(refresh_row)
            refresh.connect("clicked", self._refresh_inventory)

            self.inventory_content = self._box(Gtk.Orientation.VERTICAL, 12)
            self.page_body.append(self.inventory_content)
            self._refresh_inventory(None)
        elif page_id == "images":
            self._show_images_page()
        elif page_id == "restore-profiles":
            self._show_restore_profiles_page()
        elif page_id == "network":
            self._show_network_page()
        elif page_id == "operation-log":
            self._show_operation_log_page()
        elif page_id == "recovery-jobs":
            self._show_recovery_jobs_page()
        elif page_id == "remote-jobs":
            self._show_remote_jobs_page()
        elif page_id == "deployments":
            self._show_deployments_page()
        elif page_id == "client-jobs":
            self._show_client_jobs_page()
        elif page_id == "repositories":
            self._show_repositories_page()
        elif page_id == "system":
            self._show_system_page()
        elif page_id == "server":
            self._show_server_status_page()
        elif page_id == "operations":
            operations_page_generation = self._page_generation
            self._capture_page_generation = operations_page_generation
            self._capture_catalog_generation = getattr(self, "_capture_catalog_generation", 0) + 1
            self.page_description.set_text("Captura, restauración y clonación local. Las escrituras destructivas exigen confirmar exactamente el destino.")

            def capture_group(title: str, description: str = "") -> Adw.PreferencesGroup:
                group = Adw.PreferencesGroup(title=title, description=description)
                self.page_body.append(group)
                return group

            def capture_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget) -> Adw.ActionRow:
                row = Adw.ActionRow(title=title)
                row.add_suffix(widget)
                row.set_activatable_widget(widget)
                group.add(row)
                return row

            def capture_action(group: Adw.PreferencesGroup, title: str, button: Gtk.Button) -> None:
                capture_row(group, title, button)

            self.capture_summary = Gtk.Label(label="Consultando inventario…", xalign=0)
            self.capture_summary.set_wrap(True)
            self.capture_summary.set_selectable(True)
            summary_group = capture_group("Inventario y selección de operación")
            capture_row(summary_group, "Dispositivos compatibles", self.capture_summary)
            self.capture_kind = Gtk.DropDown.new_from_strings(["Capturar disco completo", "Capturar partición", "Capturar volumen lógico", "Capturar filesystem Stratis", "Capturar subvolumen Btrfs", "Recibir stream Btrfs", "Recuperar disco con ddrescue", "Finalizar recuperación ddrescue", "Restaurar disco", "Restaurar partición", "Restaurar volumen lógico", "Clonar disco", "Clonar partición", "Restaurar filesystem Stratis", "Construir ISO de recuperación", "Construir bundle de despliegue", "Restauración proporcional a disco menor", "Capturar disco virtual QCOW2 (P2V)"])
            self.capture_kind.connect("notify::selected", self._capture_mode_changed)
            capture_row(summary_group, "Operación", self.capture_kind)

            source_group = capture_group("Origen, destino e imagen")
            self.capture_source = Gtk.DropDown.new_from_strings(["Cargando dispositivos…"])
            self.capture_source_label = capture_row(source_group, "Origen", self.capture_source)
            self.capture_target = Gtk.DropDown.new_from_strings(["Cargando dispositivos…"])
            self.capture_target_label = capture_row(source_group, "Destino", self.capture_target)
            self.capture_image_select = Gtk.DropDown.new_from_strings(["Cargando imágenes…"])
            self.capture_image_select_label = capture_row(source_group, "Imagen existente", self.capture_image_select)
            self.capture_source.connect("notify::selected", self._update_capture_confirmation_hint)
            self.capture_target.connect("notify::selected", self._update_capture_confirmation_hint)
            self.capture_image_select.connect("notify::selected", self._update_capture_confirmation_hint)
            self.capture_repository = Gtk.DropDown.new_from_strings(["Cargando repositorios…"])
            self.capture_repository.connect("notify::selected", self._capture_repository_changed)
            self.capture_repository_label = capture_row(source_group, "Repositorio de imágenes", self.capture_repository)

            confirmation_group = capture_group("Confirmación y generación", "Las acciones destructivas requieren la frase exacta asociada al destino.")
            self.capture_confirmation = Gtk.Entry()
            self.capture_confirmation_label = capture_row(confirmation_group, "Confirmación destructiva", self.capture_confirmation)
            self.capture_confirmation.set_placeholder_text("ERASE /dev/… o BUILD <imagen>")
            self.capture_base_iso = Gtk.Entry()
            self.capture_base_iso_label = capture_row(confirmation_group, "Ruta absoluta de la ISO base", self.capture_base_iso)
            self.capture_base_iso.set_placeholder_text("/ruta/absoluta/feclora-live.iso")
            self.capture_target_wwn = Gtk.Entry()
            self.capture_target_wwn_row = capture_row(confirmation_group, "WWN destino (opcional)", self.capture_target_wwn)
            self.capture_target_wwn.set_placeholder_text("WWN destino (opcional)")
            self.capture_target_serial = Gtk.Entry()
            self.capture_target_serial_row = capture_row(confirmation_group, "Número de serie destino (opcional)", self.capture_target_serial)
            self.capture_target_serial.set_placeholder_text("Número de serie destino (opcional)")
            self.capture_bundle_name = Gtk.Entry()
            self.capture_bundle_name_label = capture_row(confirmation_group, "Nombre del bundle", self.capture_bundle_name)
            self.capture_bundle_name.set_text("fleet-deployment-bundle")
            self.capture_deployment_job_scroller = Gtk.ScrolledWindow()
            self.capture_deployment_job_label = capture_row(confirmation_group, "DeploymentJob (JSON)", self.capture_deployment_job_scroller)
            self.capture_deployment_job = Gtk.TextView()
            self.capture_deployment_job.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.capture_deployment_job.set_size_request(-1, 140)
            self.capture_deployment_job_scroller.set_child(self.capture_deployment_job)

            btrfs_group = capture_group("Btrfs", "Rutas absolutas para captura incremental y recepción de streams.")
            self.capture_btrfs_source = Gtk.Entry()
            self.capture_btrfs_source_row = capture_row(btrfs_group, "Ruta absoluta del subvolumen Btrfs", self.capture_btrfs_source)
            self.capture_btrfs_source.set_placeholder_text("/ruta/al/subvolumen")
            self.capture_btrfs_parent = Gtk.Entry()
            self.capture_btrfs_parent_row = capture_row(btrfs_group, "Padre incremental (opcional)", self.capture_btrfs_parent)
            self.capture_btrfs_parent.set_placeholder_text("Opcional: ruta del subvolumen padre")
            self.capture_btrfs_target = Gtk.Entry()
            self.capture_btrfs_target_row = capture_row(btrfs_group, "Directorio destino Btrfs ya montado", self.capture_btrfs_target)
            self.capture_btrfs_target.set_placeholder_text("/directorio/destino/montado")
            self.capture_btrfs_receive_parent = Gtk.Entry()
            self.capture_btrfs_receive_parent_row = capture_row(btrfs_group, "Padre recibido (opcional)", self.capture_btrfs_receive_parent)
            self.capture_btrfs_receive_parent.set_placeholder_text("Opcional: ruta del subvolumen padre recibido")

            format_group = capture_group("Formato y protección")
            self.capture_image_id = Gtk.Entry()
            self.capture_image_id_label = capture_row(format_group, "Identificador de imagen", self.capture_image_id)
            self.capture_image_id.set_placeholder_text("Identificador de imagen")
            self.capture_format = Gtk.DropDown.new_from_strings(["RAW de Feclora", "QCOW2"])
            self.capture_format_label = capture_row(format_group, "Formato de imagen", self.capture_format)
            self.capture_compression = Gtk.DropDown.new_from_strings(["Zstandard", "LZ4", "Gzip", "XZ", "Sin compresión"])
            self.capture_compression_row = capture_row(format_group, "Compresión", self.capture_compression)
            self.capture_encrypt = Gtk.CheckButton(label="Cifrar con destinatarios age")
            self.capture_encrypt_row = capture_row(format_group, "Cifrado con destinatarios", self.capture_encrypt)
            self.capture_passphrase_toggle = Gtk.CheckButton(label="Cifrar con frase secreta de un solo uso")
            self.capture_passphrase_toggle_row = capture_row(format_group, "Cifrado con frase secreta", self.capture_passphrase_toggle)
            self.capture_passphrase = Gtk.PasswordEntry()
            self.capture_passphrase_row = capture_row(format_group, "Frase secreta de un solo uso", self.capture_passphrase)
            self.capture_passphrase.set_show_peek_icon(True)
            self.capture_passphrase.set_placeholder_text("Frase age de un solo uso (solo disco RAW)")
            self.capture_encrypt.connect("toggled", self._capture_encryption_changed)
            self.capture_passphrase_toggle.connect("toggled", self._capture_encryption_changed)
            self.capture_format.connect("notify::selected", self._capture_mode_changed)
            self.capture_passphrase_row.set_visible(False)
            self.capture_passphrase_toggle_row.set_visible(False)

            recovery_group = capture_group("Recuperación ddrescue")
            self.capture_retry = Gtk.DropDown.new_from_strings(["3"])
            self.capture_retry_row = capture_row(recovery_group, "Pasadas de reintento (fijas)", self.capture_retry)
            self.capture_retry.set_selected(0)
            self.capture_retry_row.set_visible(False)
            self.capture_resume = Gtk.CheckButton(label="Reanudar recuperación existente (mapfile)")
            self.capture_resume_row = capture_row(recovery_group, "Reanudar recuperación", self.capture_resume)

            execution_group = capture_group("Ejecución y seguimiento")
            self.capture_start = Gtk.Button(label="Iniciar captura de disco")
            self.capture_start.connect("clicked", self._start_disk_capture)
            capture_action(execution_group, "Iniciar operación", self.capture_start)
            self.capture_cancel = Gtk.Button(label="Solicitar cancelación")
            self.capture_cancel.set_sensitive(False)
            self.capture_cancel.connect("clicked", self._cancel_disk_capture)
            capture_action(execution_group, "Cancelar operación activa", self.capture_cancel)
            self.capture_progress = Gtk.ProgressBar()
            self.capture_progress.set_show_text(True)
            capture_row(execution_group, "Progreso", self.capture_progress)
            self.capture_result = Gtk.Label(label="", xalign=0)
            self.capture_result.set_wrap(True)
            self.capture_result.set_selectable(True)
            capture_row(execution_group, "Resultado", self.capture_result)

            self.api.submit(
                "inventory",
                on_success=lambda response: self._populate_capture_devices(response)
                if operations_page_generation == self._page_generation else None,
                on_error=lambda error: self._capture_failed(error)
                if operations_page_generation == self._page_generation else None,
            )
            self._capture_remote_repositories = None
            self._capture_s3_repositories = None
            self.api.submit(
                "remote_repositories",
                on_success=lambda response: self._populate_capture_repositories(response)
                if operations_page_generation == self._page_generation else None,
                on_error=lambda error: self._capture_failed(error)
                if operations_page_generation == self._page_generation else None,
            )
            self.api.submit(
                "s3_repositories",
                on_success=lambda response: self._populate_capture_s3_repositories(response)
                if operations_page_generation == self._page_generation else None,
                on_error=lambda error: self._capture_failed(error)
                if operations_page_generation == self._page_generation else None,
            )

            active_operation_id = getattr(self, "active_capture_id", None)
            if active_operation_id:
                self.capture_start.set_sensitive(False)
                self.capture_cancel.set_sensitive(True)
                self.capture_result.set_text("Recuperando seguimiento de la operación " + active_operation_id + "…")
                self._poll_capture_status(active_operation_id, operations_page_generation)

        else:
            self.page_description.set_text("Esta pantalla aún no se ha migrado. Sus operaciones permanecen disponibles en la interfaz de producción.")

    def _history_page(self, title: str, columns: tuple[str, ...], action: str, key: str, renderer: Any) -> None:
        self._history_page_generation = self._page_generation
        self.page_description.set_text(title)
        history_group = Adw.PreferencesGroup(title="Consulta del historial")
        self.page_body.append(history_group)
        self.history_summary = Gtk.Label(label="Consultando registros…", xalign=0)
        summary_row = Adw.ActionRow(title="Estado", subtitle=title)
        summary_row.add_suffix(self.history_summary)
        history_group.add(summary_row)
        refresh = Gtk.Button(label="Actualizar")
        refresh.connect("clicked", lambda _button: self._refresh_history(action, key, renderer))
        refresh_row = Adw.ActionRow(title="Actualizar historial")
        refresh_row.add_suffix(refresh)
        refresh_row.set_activatable_widget(refresh)
        history_group.add(refresh_row)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.history_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.history_grid)
        self.page_body.append(scroller)
        self.history_columns = columns
        self._refresh_history(action, key, renderer)

    def _refresh_history(self, action: str, key: str, renderer: Any) -> None:
        self._history_refresh_generation = getattr(self, "_history_refresh_generation", 0) + 1
        generation = self._history_refresh_generation
        page_generation = self._history_page_generation
        self.history_summary.set_text("Consultando " + action + "…")
        self.api.submit(
            action,
            on_success=lambda response: self._show_history_rows(response, key, renderer)
            if page_generation == self._page_generation and generation == self._history_refresh_generation else None,
            on_error=lambda error: self._history_failed(error)
            if page_generation == self._page_generation and generation == self._history_refresh_generation else None,
        )

    def _show_history_rows(self, response: dict[str, Any], key: str, renderer: Any) -> None:
        grid = self.history_grid
        while child := grid.get_first_child():
            grid.remove(child)
        for column, heading in enumerate(self.history_columns):
            label = Gtk.Label(label=heading, xalign=0)
            label.add_css_class("heading")
            grid.attach(label, column, 0, 1, 1)
        rows = response.get(key) or []
        for row, item in enumerate(rows, start=1):
            for column, value in enumerate(renderer(item)):
                label = Gtk.Label(label=str(value), xalign=0)
                label.set_selectable(True)
                label.set_wrap(True)
                grid.attach(label, column, row, 1, 1)
        self.history_summary.set_text(f"Registros: {len(rows)}")

    def _history_failed(self, error: Exception) -> None:
        self.history_summary.set_text("No se pudieron consultar los registros: " + str(error))

    def _show_system_page(self) -> None:
        self.page_description.set_text("Estado del sistema, servicios y certificados detectados por el backend privilegiado.")
        system_group = Adw.PreferencesGroup(
            title="Estado del sistema",
            description="Información obtenida del backend privilegiado; esta vista no modifica la configuración.",
        )
        self.status_summary = Gtk.Label(label="Consultando estado del sistema…", xalign=0)
        self.status_summary.set_wrap(True)
        self.status_summary.set_selectable(True)
        self.status_summary.set_max_width_chars(72)
        status_row = Adw.ActionRow(title="Resumen del sistema")
        status_row.set_subtitle("Host, plataforma, servicios y certificados")
        status_row.add_suffix(self.status_summary)
        system_group.add(status_row)
        refresh = Gtk.Button(label="Actualizar")
        refresh.set_valign(Gtk.Align.CENTER)
        refresh.connect("clicked", self._refresh_status)
        refresh_row = Adw.ActionRow(title="Actualizar estado")
        refresh_row.set_subtitle("Consultar de nuevo el estado actual")
        refresh_row.add_suffix(refresh)
        refresh_row.set_activatable_widget(refresh)
        system_group.add(refresh_row)
        self.page_body.append(system_group)
        self.system_details_group = Adw.PreferencesGroup(
            title="Configuración, servicios y certificados",
            description="Desglose equivalente al estado del sistema mostrado por la interfaz Textual.",
        )
        self.page_body.append(self.system_details_group)
        self._refresh_status(None)

    def _show_server_status_page(self) -> None:
        self._server_status_page_generation = getattr(self, "_server_status_page_generation", 0) + 1
        self._server_window_page_generation = self._page_generation
        self.page_description.set_text("Administración del servidor, TLS, PXE, publicación/revocación de respuestas y gestión de destinatarios age.")

        def add_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget) -> Adw.ActionRow:
            row = Adw.ActionRow(title=title)
            row.add_suffix(widget)
            row.set_activatable_widget(widget)
            group.add(row)
            if isinstance(widget, Gtk.Entry):
                widget.set_hexpand(True)
                widget.set_width_chars(24)
            return row

        status_group = Adw.PreferencesGroup(
            title="Estado del servidor",
            description="Salud de los servicios PXE, identidad TLS y estado operativo",
        )
        self.page_body.append(status_group)
        self.server_status = Gtk.Label(label="Consultando estado del servidor…", xalign=0)
        self.server_status.set_wrap(True)
        self.server_status.set_selectable(True)
        status_row = Adw.ActionRow(title="Resumen")
        status_row.set_subtitle("Estado consultado a través de la API privilegiada")
        status_row.add_suffix(self.server_status)
        status_group.add(status_row)
        refresh = Gtk.Button(label="Actualizar")
        refresh.connect("clicked", self._refresh_server_status)
        add_row(status_group, "Actualizar estado", refresh)

        server_group = Adw.PreferencesGroup(
            title="Identidad y certificados TLS",
            description="Preparación inicial y operaciones de mantenimiento protegidas por confirmación exacta",
        )
        self.page_body.append(server_group)
        self.server_interface = Gtk.DropDown.new_from_strings(["Actualiza interfaces…"])
        add_row(server_group, "Interfaz del servidor", self.server_interface)
        bootstrap = Gtk.Button(label="Preparar identidad TLS")
        bootstrap.connect("clicked", self._bootstrap_server)
        add_row(server_group, "Preparación inicial", bootstrap)
        self.server_renew_confirmation = Gtk.Entry()
        self.server_renew_confirmation.set_placeholder_text("Escribe RENEW SERVER CERTIFICATE")
        add_row(server_group, "Confirmación de renovación", self.server_renew_confirmation)
        renew = Gtk.Button(label="Renovar certificado")
        renew.connect("clicked", self._renew_server_certificate)
        add_row(server_group, "Renovación TLS", renew)
        self.server_rotate_confirmation = Gtk.Entry()
        self.server_rotate_confirmation.set_placeholder_text("Escribe ROTATE SERVER TLS KEYPAIR")
        add_row(server_group, "Confirmación de rotación", self.server_rotate_confirmation)
        rotate = Gtk.Button(label="Rotar clave TLS")
        rotate.connect("clicked", self._rotate_server_keypair)
        add_row(server_group, "Rotación de clave", rotate)

        pxe_group = Adw.PreferencesGroup(
            title="Servicios PXE",
            description="Define y valida el perfil de red antes de iniciar los servicios",
        )
        self.page_body.append(pxe_group)
        self.pxe_mode = Gtk.DropDown.new_from_strings(["Proxy DHCP (red existente)", "Red aislada (DHCP autoritativo)"])
        add_row(pxe_group, "Modo de red", self.pxe_mode)
        self.pxe_pool_start = Gtk.Entry()
        self.pxe_pool_start.set_text("192.168.50.100")
        self.pxe_pool_start_row = add_row(pxe_group, "Inicio del rango DHCP", self.pxe_pool_start)
        self.pxe_pool_end = Gtk.Entry()
        self.pxe_pool_end.set_text("192.168.50.200")
        self.pxe_pool_end_row = add_row(pxe_group, "Fin del rango DHCP", self.pxe_pool_end)
        self.pxe_lease = Gtk.Entry()
        self.pxe_lease.set_text("1h")
        add_row(pxe_group, "Duración de concesión", self.pxe_lease)
        self.pxe_gateway = Gtk.Entry()
        self.pxe_gateway.set_placeholder_text("Gateway IPv4 opcional")
        self.pxe_gateway_row = add_row(pxe_group, "Gateway IPv4", self.pxe_gateway)
        self.pxe_dns = Gtk.Entry()
        self.pxe_dns.set_placeholder_text("Servidor DNS IPv4 opcional")
        self.pxe_dns_row = add_row(pxe_group, "Servidor DNS IPv4", self.pxe_dns)
        self.pxe_port = Gtk.Entry()
        self.pxe_port.set_text("8080")
        add_row(pxe_group, "Puerto HTTP", self.pxe_port)
        self.pxe_max_clients = Gtk.Entry()
        self.pxe_max_clients.set_placeholder_text("Máximo de clientes (opcional)")
        add_row(pxe_group, "Límite de clientes", self.pxe_max_clients)
        self.pxe_max_duration = Gtk.Entry()
        self.pxe_max_duration.set_placeholder_text("Duración máxima en segundos (opcional)")
        add_row(pxe_group, "Duración máxima", self.pxe_max_duration)
        self.pxe_authoritative = Gtk.CheckButton(label="Confirmo que esta interfaz/red puede servir DHCP autoritativo")
        self.pxe_authoritative_row = add_row(pxe_group, "Autorización DHCP", self.pxe_authoritative)
        for field in (
            self.pxe_pool_start, self.pxe_pool_end, self.pxe_lease, self.pxe_gateway,
            self.pxe_dns, self.pxe_port, self.pxe_max_clients, self.pxe_max_duration,
        ):
            field.connect("changed", self._pxe_inputs_changed)
        self.pxe_authoritative.connect("toggled", self._pxe_inputs_changed)
        self.server_interface.connect("notify::selected", self._pxe_inputs_changed)
        validate = Gtk.Button(label="Validar perfil")
        validate.connect("clicked", self._validate_pxe_profile)
        add_row(pxe_group, "Preflight sin cambios", validate)
        self.pxe_start = Gtk.Button(label="Iniciar servicios PXE")
        self.pxe_start.set_sensitive(False)
        self.pxe_start.connect("clicked", self._start_pxe_services)
        add_row(pxe_group, "Inicio PXE", self.pxe_start)
        stop = Gtk.Button(label="Detener servicios PXE")
        stop.connect("clicked", self._stop_pxe_services)
        add_row(pxe_group, "Parada PXE", stop)
        self.pxe_result = Gtk.Label(label="Perfil PXE no validado.", xalign=0)
        self.pxe_result.set_wrap(True)
        self.pxe_result.set_selectable(True)
        result_row = Adw.ActionRow(title="Resultado de validación")
        result_row.add_suffix(self.pxe_result)
        pxe_group.add(result_row)
        self._pxe_profile = None
        self.pxe_mode.connect("notify::selected", self._pxe_mode_changed)
        self._pxe_mode_changed(self.pxe_mode)

        answer_group = Adw.PreferencesGroup(
            title="Respuestas PXE desatendidas",
            description="Validación, publicación y revocación de respuestas de instalación",
        )
        self.page_body.append(answer_group)
        self.pxe_answer_source = Gtk.DropDown.new_from_strings(["Archivo local", "URL HTTP/HTTPS", "Repositorio", "SCP · SSHFS"])
        add_row(answer_group, "Origen de respuesta", self.pxe_answer_source)
        self.pxe_answer_job_id = Gtk.Entry()
        self.pxe_answer_job_id.set_placeholder_text("UUID del DeploymentJob (opcional para archivo local)")
        add_row(answer_group, "DeploymentJob", self.pxe_answer_job_id)
        self.pxe_answer_path = Gtk.Entry()
        self.pxe_answer_path.set_placeholder_text("Ruta local / URL / ruta relativa en repositorio")
        add_row(answer_group, "Ruta o URL", self.pxe_answer_path)
        self.pxe_answer_repository = Gtk.DropDown.new_from_strings(["Selecciona repositorio…"])
        add_row(answer_group, "Repositorio", self.pxe_answer_repository)
        publish = Gtk.Button(label="Validar y publicar respuesta PXE")
        publish.connect("clicked", self._publish_pxe_answer)
        add_row(answer_group, "Publicación", publish)
        self.pxe_answer_revoke_id = Gtk.Entry()
        self.pxe_answer_revoke_id.set_placeholder_text("UUID de respuesta publicada")
        add_row(answer_group, "ID de respuesta", self.pxe_answer_revoke_id)
        revoke = Gtk.Button(label="Revocar respuesta PXE")
        revoke.connect("clicked", self._revoke_pxe_answer)
        add_row(answer_group, "Revocación", revoke)
        self.pxe_answer_result = Gtk.Label(label="Sin publicación solicitada.", xalign=0)
        self.pxe_answer_result.set_wrap(True)
        self.pxe_answer_result.set_selectable(True)
        answer_result_row = Adw.ActionRow(title="Resultado")
        answer_result_row.add_suffix(self.pxe_answer_result)
        answer_group.add(answer_result_row)

        age_group = Adw.PreferencesGroup(
            title="Cifrado age y destinatarios",
            description="Exportación del servidor, inventario del cliente y entrega de frases de un solo uso",
        )
        self.page_body.append(age_group)
        self.server_age_directory = Gtk.Entry()
        self.server_age_directory.set_placeholder_text("Directorio de exportación protegido del servidor")
        add_row(age_group, "Directorio de exportación", self.server_age_directory)
        export_age = Gtk.Button(label="Exportar destinatarios age")
        export_age.connect("clicked", self._export_server_age_recipients)
        add_row(age_group, "Destinatarios del servidor", export_age)
        self.client_age_path = Gtk.Entry()
        self.client_age_path.set_placeholder_text("Ruta del inventario age del cliente")
        add_row(age_group, "Inventario del cliente", self.client_age_path)
        refresh_age = Gtk.Button(label="Actualizar inventario age")
        refresh_age.connect("clicked", self._refresh_client_age_recipients)
        add_row(age_group, "Actualizar destinatarios", refresh_age)
        self.pxe_passphrase_status = Gtk.Label(label="Consultando solicitud age…", xalign=0)
        self.pxe_passphrase_status.set_wrap(True)
        passphrase_status_row = Adw.ActionRow(title="Solicitud de frase age")
        passphrase_status_row.add_suffix(self.pxe_passphrase_status)
        age_group.add(passphrase_status_row)
        refresh_passphrase = Gtk.Button(label="Actualizar estado")
        refresh_passphrase.connect("clicked", lambda _button: self._refresh_pxe_passphrase_status())
        add_row(age_group, "Estado de solicitud", refresh_passphrase)
        self.pxe_passphrase = Gtk.Entry()
        self.pxe_passphrase.set_visibility(False)
        self.pxe_passphrase.set_placeholder_text("Frase age de un solo uso")
        add_row(age_group, "Frase age", self.pxe_passphrase)
        passphrase_button = Gtk.Button(label="Entregar frase al worker PXE")
        passphrase_button.connect("clicked", self._submit_pxe_passphrase)
        add_row(age_group, "Entrega de secreto", passphrase_button)

        self._refresh_pxe_answer_repositories()
        self._refresh_pxe_passphrase_status()
        self._refresh_server_status(None)

    def _refresh_server_status(self, _button: Gtk.Button | None) -> None:
        self._server_status_refresh_generation = getattr(self, "_server_status_refresh_generation", 0) + 1
        generation = self._server_status_refresh_generation
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.server_status_parts: dict[str, Any] = {}
        self.server_status.set_text("Consultando estado, PXE e interfaces…")
        for action, key in (("status", "status"), ("pxe_service_status", "pxe"), ("network_interfaces", "interfaces")):
            self.api.submit(
                action,
                on_success=lambda value, part=key: self._server_status_part(part, value, generation)
                if page_generation == self._server_status_page_generation
                and window_generation == self._page_generation
                and generation == self._server_status_refresh_generation else None,
                on_error=lambda error: self._server_status_failed(error, generation)
                if page_generation == self._server_status_page_generation
                and window_generation == self._page_generation
                and generation == self._server_status_refresh_generation else None,
            )

    def _server_action_done(
        self, result: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        self._server_action_result = result
        self._server_action_results = getattr(self, "_server_action_results", [])
        self._server_action_results.append(result)
        if page_generation is not None and (page_generation != self._server_status_page_generation or window_generation != self._page_generation):
            return
        message = result.get("message") or str(result)
        self.server_status.set_text(str(message))
        self._refresh_server_status(None)

    def _server_action_failed(
        self, error: Exception, page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        self._server_action_errors = getattr(self, "_server_action_errors", [])
        self._server_action_errors.append(str(error))
        if page_generation is not None and (page_generation != self._server_status_page_generation or window_generation != self._page_generation):
            return
        self.server_status.set_text("Error de administración del servidor: " + str(error))

    def _selected_server_interface(self) -> dict[str, Any] | None:
        selected = self.server_interface.get_selected()
        interfaces = getattr(self, "server_interfaces", [])
        if selected == 0 or selected > len(interfaces):
            return None
        return interfaces[selected - 1]

    def _bootstrap_server(self, _button: Gtk.Button) -> None:
        selected = self._selected_server_interface()
        if not selected:
            self.server_status.set_text("Selecciona una interfaz con dirección IPv4.")
            return
        params = {
            "interface": selected.get("interface"), "address": selected.get("address"),
            "prefix_length": selected.get("prefix_length"),
        }
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit("bootstrap_server", params, on_success=lambda result, page=page_generation, window=window_generation: self._server_action_done(result, page, window), on_error=lambda error, page=page_generation, window=window_generation: self._server_action_failed(error, page, window))

    def _renew_server_certificate(self, _button: Gtk.Button) -> None:
        confirmation = self.server_renew_confirmation.get_text().strip()
        if confirmation != "RENEW SERVER CERTIFICATE":
            self.server_status.set_text("Escribe exactamente RENEW SERVER CERTIFICATE.")
            return
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit("renew_server_certificate", {"confirmation": confirmation}, on_success=lambda result, page=page_generation, window=window_generation: self._server_action_done(result, page, window), on_error=lambda error, page=page_generation, window=window_generation: self._server_action_failed(error, page, window))
        self.server_renew_confirmation.set_text("")

    def _rotate_server_keypair(self, _button: Gtk.Button) -> None:
        confirmation = self.server_rotate_confirmation.get_text().strip()
        if confirmation != "ROTATE SERVER TLS KEYPAIR":
            self.server_status.set_text("Escribe exactamente ROTATE SERVER TLS KEYPAIR.")
            return
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit("rotate_server_keypair", {"confirmation": confirmation}, on_success=lambda result, page=page_generation, window=window_generation: self._server_action_done(result, page, window), on_error=lambda error, page=page_generation, window=window_generation: self._server_action_failed(error, page, window))
        self.server_rotate_confirmation.set_text("")

    def _invalidate_pxe_validation(self) -> None:
        self._pxe_validation_generation = getattr(self, "_pxe_validation_generation", 0) + 1
        self._pxe_profile = None
        self._pxe_pending_profile = None
        self.pxe_start.set_sensitive(False)
        self.pxe_result.set_text("Perfil PXE no validado.")

    def _pxe_inputs_changed(self, *_args: Any) -> None:
        self._invalidate_pxe_validation()

    def _pxe_mode_changed(self, _widget: Gtk.DropDown, _pspec: Any = None) -> None:
        isolated = self.pxe_mode.get_selected() == 1
        for row in (
            self.pxe_pool_start_row, self.pxe_pool_end_row,
            self.pxe_gateway_row, self.pxe_dns_row, self.pxe_authoritative_row,
        ):
            row.set_visible(isolated)
        # A profile validated for the previous DHCP mode must never be startable.
        self._invalidate_pxe_validation()

    def _validate_pxe_profile(self, _button: Gtk.Button) -> None:
        selected = self._selected_server_interface()
        if not selected:
            self.pxe_result.set_text("Selecciona la interfaz y dirección IPv4 del servidor.")
            return
        try:
            port = int(self.pxe_port.get_text().strip())
            max_clients_text = self.pxe_max_clients.get_text().strip()
            max_duration_text = self.pxe_max_duration.get_text().strip()
            mode = "isolated" if self.pxe_mode.get_selected() == 1 else "proxy"
            profile = {
                "interface": selected["interface"], "address": selected["address"],
                "prefix_length": selected["prefix_length"], "mode": mode,
                "pool_start": self.pxe_pool_start.get_text().strip() or None if mode == "isolated" else None,
                "pool_end": self.pxe_pool_end.get_text().strip() or None if mode == "isolated" else None,
                "lease_time": self.pxe_lease.get_text().strip(),
                "gateway": self.pxe_gateway.get_text().strip() or None if mode == "isolated" else None,
                "dns_server": self.pxe_dns.get_text().strip() or None if mode == "isolated" else None,
                "http_port": port,
                "authoritative_confirmed": self.pxe_authoritative.get_active() if mode == "isolated" else False,
                "max_clients": int(max_clients_text) if max_clients_text else None,
                "max_duration_seconds": int(max_duration_text) if max_duration_text else None,
            }
        except ValueError:
            self.pxe_result.set_text("Puerto, límite de clientes y duración deben ser números enteros.")
            self.pxe_start.set_sensitive(False)
            self._pxe_profile = None
            return
        self.pxe_result.set_text("Validando perfil PXE…")
        self.pxe_start.set_sensitive(False)
        self._pxe_profile = None
        self._pxe_validation_generation = getattr(self, "_pxe_validation_generation", 0) + 1
        generation = self._pxe_validation_generation
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self._pxe_pending_profile = profile
        self.api.submit(
            "validate_pxe_profile", profile,
            on_success=lambda result, token=generation, page=page_generation, window=window_generation, snapshot=dict(profile): self._pxe_profile_validated(result, token, page, window, snapshot),
            on_error=lambda error, token=generation, page=page_generation, window=window_generation: self._pxe_profile_rejected(error, token, page, window),
        )

    def _pxe_profile_validated(self, result: dict[str, Any], generation: int | None = None, page_generation: int | None = None, window_generation: int | None = None, profile: dict[str, Any] | None = None) -> None:
        if generation != self._pxe_validation_generation or page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        self._pxe_profile = profile
        if self._pxe_profile is None:
            self.pxe_result.set_text("No se conservó el perfil validado; vuelve a validarlo.")
            return
        self.pxe_start.set_sensitive(True)
        self.pxe_result.set_text(str(result.get("message") or result))

    def _pxe_profile_rejected(self, error: Exception, generation: int | None = None, page_generation: int | None = None, window_generation: int | None = None) -> None:
        if generation != self._pxe_validation_generation or page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        self._pxe_profile = None
        self.pxe_start.set_sensitive(False)
        self.pxe_result.set_text("El perfil PXE no pasó la validación: " + str(error))

    def _start_pxe_services(self, _button: Gtk.Button) -> None:
        if self._pxe_profile is None:
            self.pxe_result.set_text("Valida un perfil PXE antes de iniciar servicios.")
            return
        self.pxe_result.set_text("Iniciando servicios PXE…")
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        profile = dict(self._pxe_profile)
        self.api.submit(
            "start_pxe_services", profile,
            on_success=lambda result, page=page_generation, window=window_generation: self._pxe_action_done(result, page, window),
            on_error=lambda error, page=page_generation, window=window_generation: self._pxe_action_failed(error, page, window),
        )

    def _stop_pxe_services(self, _button: Gtk.Button) -> None:
        self.pxe_result.set_text("Deteniendo servicios PXE…")
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit(
            "stop_pxe_services",
            on_success=lambda result, page=page_generation, window=window_generation: self._pxe_action_done(result, page, window),
            on_error=lambda error, page=page_generation, window=window_generation: self._pxe_action_failed(error, page, window),
        )

    def _pxe_action_done(
        self, result: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        self._pxe_action_result = result
        self._pxe_action_results = getattr(self, "_pxe_action_results", [])
        self._pxe_action_results.append(result)
        if page_generation is not None and (page_generation != self._server_status_page_generation or window_generation != self._page_generation):
            return
        self.pxe_result.set_text(str(result.get("message") or result))
        self._refresh_server_status(None)

    def _pxe_action_failed(
        self, error: Exception, page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        self._pxe_action_errors = getattr(self, "_pxe_action_errors", [])
        self._pxe_action_errors.append(str(error))
        if page_generation is not None and (page_generation != self._server_status_page_generation or window_generation != self._page_generation):
            return
        self.pxe_result.set_text("Error en servicios PXE: " + str(error))

    def _refresh_pxe_answer_repositories(self) -> None:
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self._pxe_answer_remote_rows = []
        self._pxe_answer_s3_rows = []
        self._pxe_answer_pending_parts = {"remote", "s3"}
        self._pxe_answer_repository_failed = False
        self.api.submit(
            "remote_repositories",
            on_success=lambda response: self._pxe_answer_remote_repositories(response, page_generation, window_generation)
            if page_generation == self._server_status_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error: self._pxe_answer_repository_error(error, page_generation, window_generation)
            if page_generation == self._server_status_page_generation and window_generation == self._page_generation else None,
        )
        self.api.submit(
            "s3_repositories",
            on_success=lambda response: self._pxe_answer_s3_repositories(response, page_generation, window_generation)
            if page_generation == self._server_status_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error: self._pxe_answer_repository_error(error, page_generation, window_generation)
            if page_generation == self._server_status_page_generation and window_generation == self._page_generation else None,
        )

    def _pxe_answer_remote_repositories(
        self, response: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._server_status_page_generation or window_generation != self._page_generation
        ):
            return
        self._pxe_answer_remote_rows = [
            item for item in response.get("repositories", [])
            if isinstance(item, dict) and item.get("mounted") and item.get("verified")
        ]
        if page_generation is None:
            self._render_pxe_answer_repositories()
        else:
            self._pxe_answer_repository_part_loaded("remote", page_generation, window_generation)

    def _pxe_answer_s3_repositories(
        self, response: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._server_status_page_generation or window_generation != self._page_generation
        ):
            return
        self._pxe_answer_s3_rows = [
            item for item in response.get("repositories", [])
            if isinstance(item, dict) and item.get("id")
        ]
        if page_generation is None:
            self._render_pxe_answer_repositories()
        else:
            self._pxe_answer_repository_part_loaded("s3", page_generation, window_generation)

    def _pxe_answer_repository_part_loaded(
        self, part: str, page_generation: int, window_generation: int | None = None
    ) -> None:
        if page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        pending = getattr(self, "_pxe_answer_pending_parts", set())
        pending.discard(part)
        if not pending and not getattr(self, "_pxe_answer_repository_failed", False):
            self._render_pxe_answer_repositories()

    def _pxe_answer_repository_error(
        self, error: Exception, page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._server_status_page_generation or window_generation != self._page_generation
        ):
            return
        self._pxe_answer_repository_failed = True
        self.pxe_answer_result.set_text("No se pudieron cargar los repositorios para respuestas PXE: " + str(error))

    def _render_pxe_answer_repositories(self) -> None:
        rows = getattr(self, "_pxe_answer_remote_rows", []) + getattr(self, "_pxe_answer_s3_rows", [])
        self._pxe_answer_repository_rows = rows
        labels = ["Selecciona repositorio…"] + [str(item.get("id")) for item in rows]
        self.pxe_answer_repository.set_model(Gtk.StringList.new(labels))
        self.pxe_answer_repository.set_selected(0)

    def _publish_pxe_answer(self, _button: Gtk.Button) -> None:
        import uuid as uuid_module
        source_index = self.pxe_answer_source.get_selected()
        source = ("upload", "url", "repository", "scp")[source_index] if source_index < 4 else ""
        value = self.pxe_answer_path.get_text().strip()
        job_id = self.pxe_answer_job_id.get_text().strip()
        request: dict[str, Any] = {"source": source}
        try:
            if source == "upload":
                if not value:
                    raise ValueError("Indica la ruta local del archivo JSON.")
                payload = Path(value).expanduser().read_bytes()
                if not 1 <= len(payload) <= 64 * 1024:
                    raise ValueError("El archivo debe tener entre 1 byte y 64 KiB.")
                if not job_id:
                    try:
                        document = json.loads(payload)
                        if isinstance(document, dict):
                            job_id = str(document.get("job_id") or "")
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                if not job_id:
                    job_id = str(uuid_module.uuid4())
                request["answer_base64"] = base64.b64encode(payload).decode("ascii")
            elif source == "url":
                if not value or not job_id:
                    raise ValueError("Indica URL HTTP/HTTPS y UUID del trabajo.")
                request["url"] = value
            elif source in {"repository", "scp"}:
                selected = self.pxe_answer_repository.get_selected()
                rows = getattr(self, "_pxe_answer_repository_rows", [])
                if selected == 0 or selected - 1 >= len(rows) or not value or not job_id:
                    raise ValueError("Selecciona repositorio, UUID y ruta relativa.")
                repository = rows[selected - 1]
                if source == "scp" and repository.get("provider") != "sshfs":
                    raise ValueError("SCP requiere un repositorio SSHFS con credenciales SSH protegidas.")
                request["repository_id"] = repository.get("id")
                request["source_path"] = value
            else:
                raise ValueError("Selecciona un origen válido.")
        except (OSError, ValueError) as error:
            self.pxe_answer_result.set_text("No se puede preparar la publicación: " + str(error))
            return
        request["job_id"] = job_id
        self.pxe_answer_result.set_text("El backend validará la respuesta y el estado activo de PXE antes de publicarla…")
        self._pxe_answer_action_generation = getattr(self, "_pxe_answer_action_generation", 0) + 1
        request_generation = self._pxe_answer_action_generation
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit(
            "publish_pxe_answer", request,
            on_success=lambda result: self._pxe_answer_published(result, page_generation, window_generation, request_generation, job_id),
            on_error=lambda error: self._pxe_answer_failed(error, page_generation, window_generation, request_generation, job_id),
        )

    def _pxe_answer_published(
        self, result: dict[str, Any], page_generation: int, window_generation: int,
        request_generation: int, requested_job_id: str,
    ) -> None:
        self._pxe_answer_action_results = getattr(self, "_pxe_answer_action_results", {})
        self._pxe_answer_action_results["publish:" + requested_job_id] = result
        if page_generation != self._server_status_page_generation or window_generation != self._page_generation or request_generation != getattr(self, "_pxe_answer_action_generation", None):
            return
        self._pxe_published_answer = result
        job_id = str(result.get("job_id") or requested_job_id)
        self.pxe_answer_revoke_id.set_text(job_id)
        self.pxe_answer_result.set_text(str(result.get("message") or result))
        self._refresh_pxe_passphrase_status()

    def _pxe_answer_failed(
        self, error: Exception, page_generation: int | None = None,
        window_generation: int | None = None, request_generation: int | None = None,
        job_id: str | None = None,
    ) -> None:
        self._pxe_answer_action_errors = getattr(self, "_pxe_answer_action_errors", {})
        self._pxe_answer_action_errors[job_id or "latest"] = str(error)
        if page_generation is not None and (
            page_generation != self._server_status_page_generation
            or window_generation != self._page_generation
            or request_generation != getattr(self, "_pxe_answer_action_generation", None)
        ):
            return
        self.pxe_answer_result.set_text("No se pudo completar la operación de respuesta PXE: " + str(error))

    def _revoke_pxe_answer(self, _button: Gtk.Button) -> None:
        job_id = self.pxe_answer_revoke_id.get_text().strip()
        if not job_id:
            self.pxe_answer_result.set_text("Indica el UUID de la respuesta que quieres revocar.")
            return
        self.pxe_answer_result.set_text("Revocando respuesta y script iPXE…")
        self._pxe_answer_action_generation = getattr(self, "_pxe_answer_action_generation", 0) + 1
        request_generation = self._pxe_answer_action_generation
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit(
            "revoke_pxe_answer", {"job_id": job_id},
            on_success=lambda result: self._pxe_answer_revoked(result, page_generation, window_generation, request_generation, job_id),
            on_error=lambda error: self._pxe_answer_failed(error, page_generation, window_generation, request_generation, job_id),
        )

    def _pxe_answer_revoked(
        self, result: dict[str, Any], page_generation: int, window_generation: int,
        request_generation: int, job_id: str,
    ) -> None:
        self._pxe_answer_action_results = getattr(self, "_pxe_answer_action_results", {})
        self._pxe_answer_action_results["revoke:" + job_id] = result
        if page_generation != self._server_status_page_generation or window_generation != self._page_generation or request_generation != getattr(self, "_pxe_answer_action_generation", None) or self.pxe_answer_revoke_id.get_text().strip() != job_id:
            return
        self._pxe_published_answer = None
        self.pxe_answer_result.set_text(str(result.get("message") or result))
        self._refresh_pxe_passphrase_status()

    def _export_server_age_recipients(self, _button: Gtk.Button) -> None:
        directory = self.server_age_directory.get_text().strip()
        if not directory:
            self.server_status.set_text("Indica el directorio de exportación protegido.")
            return
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit("export_server_age_recipients", {"export_directory": directory}, on_success=lambda result, page=page_generation, window=window_generation: self._server_action_done(result, page, window), on_error=lambda error, page=page_generation, window=window_generation: self._server_action_failed(error, page, window))

    def _refresh_client_age_recipients(self, _button: Gtk.Button) -> None:
        path = self.client_age_path.get_text().strip()
        if not path:
            self.server_status.set_text("Indica la ruta del inventario de destinatarios del cliente.")
            return
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.api.submit("refresh_client_age_recipients", {"inventory_path": path}, on_success=lambda result, page=page_generation, window=window_generation: self._server_action_done(result, page, window), on_error=lambda error, page=page_generation, window=window_generation: self._server_action_failed(error, page, window))

    def _refresh_pxe_passphrase_status(self) -> None:
        self._pxe_passphrase_status_generation = getattr(self, "_pxe_passphrase_status_generation", 0) + 1
        request_generation = self._pxe_passphrase_status_generation
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.pxe_passphrase_status.set_text("Consultando estado de la solicitud age…")
        self.api.submit(
            "pxe_age_passphrase_status",
            on_success=lambda result: self._pxe_passphrase_status_loaded(result, request_generation, page_generation, window_generation),
            on_error=lambda error: self._pxe_passphrase_status_failed(error, request_generation, page_generation, window_generation),
        )

    def _pxe_passphrase_status_loaded(
        self, result: dict[str, Any], request_generation: int | None = None,
        page_generation: int | None = None, window_generation: int | None = None,
    ) -> None:
        self._pxe_passphrase_status_result = result
        if request_generation != getattr(self, "_pxe_passphrase_status_generation", None) or page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        if result.get("waiting"):
            self.pxe_passphrase_status.set_text("El worker PXE está esperando una frase age de un solo uso.")
            self.pxe_passphrase.set_sensitive(True)
        elif result.get("submitted"):
            self.pxe_passphrase_status.set_text("La frase ya fue entregada al worker PXE.")
            self.pxe_passphrase.set_sensitive(False)
        elif result.get("available"):
            self.pxe_passphrase_status.set_text("No hay ninguna frase age pendiente.")
            self.pxe_passphrase.set_sensitive(False)
        else:
            self.pxe_passphrase_status.set_text("Este entorno no es un cliente Live PXE desatendido.")
            self.pxe_passphrase.set_sensitive(False)

    def _pxe_passphrase_status_failed(
        self, error: Exception, request_generation: int | None = None,
        page_generation: int | None = None, window_generation: int | None = None,
    ) -> None:
        self._pxe_passphrase_status_errors = getattr(self, "_pxe_passphrase_status_errors", [])
        self._pxe_passphrase_status_errors.append(str(error))
        if request_generation != getattr(self, "_pxe_passphrase_status_generation", None) or page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        self.pxe_passphrase_status.set_text("No se pudo consultar la solicitud age: " + str(error))
        self.pxe_passphrase.set_sensitive(False)

    def _submit_pxe_passphrase(self, _button: Gtk.Button) -> None:
        passphrase = self.pxe_passphrase.get_text()
        if not passphrase:
            self.pxe_passphrase_status.set_text("Introduce la frase age pendiente.")
            return
        self._pxe_passphrase_submit_generation = getattr(self, "_pxe_passphrase_submit_generation", 0) + 1
        request_generation = self._pxe_passphrase_submit_generation
        page_generation = self._server_status_page_generation
        window_generation = self._server_window_page_generation
        self.pxe_passphrase.set_sensitive(False)
        self.api.submit(
            "provide_pxe_age_passphrase", {"passphrase": passphrase},
            on_success=lambda result: self._pxe_passphrase_submitted(result, request_generation, page_generation, window_generation),
            on_error=lambda error: self._pxe_passphrase_submit_failed(error, request_generation, page_generation, window_generation),
        )

    def _pxe_passphrase_submitted(
        self, result: dict[str, Any], request_generation: int | None = None,
        page_generation: int | None = None, window_generation: int | None = None,
    ) -> None:
        self._pxe_passphrase_submit_result = result
        if request_generation != getattr(self, "_pxe_passphrase_submit_generation", None) or page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        self.pxe_passphrase.set_text("")
        self.pxe_passphrase_status.set_text(str(result.get("message") or result))
        self._refresh_pxe_passphrase_status()

    def _pxe_passphrase_submit_failed(
        self, error: Exception, request_generation: int | None = None,
        page_generation: int | None = None, window_generation: int | None = None,
    ) -> None:
        self._pxe_passphrase_submit_errors = getattr(self, "_pxe_passphrase_submit_errors", [])
        self._pxe_passphrase_submit_errors.append(str(error))
        if request_generation != getattr(self, "_pxe_passphrase_submit_generation", None) or page_generation != self._server_status_page_generation or window_generation != self._page_generation:
            return
        self.pxe_passphrase.set_sensitive(True)
        self.pxe_passphrase_status.set_text("No se pudo entregar la frase age: " + str(error))

    def _server_status_part(
        self, key: str, value: dict[str, Any], generation: int | None = None
    ) -> None:
        if generation is not None and generation != self._server_status_refresh_generation:
            return
        self.server_status_parts[key] = value
        if set(self.server_status_parts) != {"status", "pxe", "interfaces"}:
            return
        status = self.server_status_parts["status"]
        pxe = self.server_status_parts["pxe"]
        interfaces = self.server_status_parts["interfaces"].get("interfaces") or []
        self.server_interfaces = [
            item for item in interfaces
            if isinstance(item, dict) and item.get("interface") and item.get("address")
            and isinstance(item.get("prefix_length"), int)
        ]
        if hasattr(self, "server_interface"):
            labels = ["Selecciona interfaz/dirección activa…"] + [
                f"{item['interface']} · {item['address']}/{item['prefix_length']}" for item in self.server_interfaces
            ]
            self.server_interface.set_model(Gtk.StringList.new(labels))
            self.server_interface.set_selected(0)
        lines = [
            f"Equipo: {status.get('hostname', '—')}",
            f"Sistema: {status.get('platform', '—')}",
            f"Servidor configurado: {'sí' if status.get('server_configured') else 'no'}",
            f"PXE: {pxe}",
        ]
        lines.extend(f"Servicio {name}: {state}" for name, state in (status.get("services") or {}).items())
        lines.extend(f"Certificado {item.get('role') or '—'}: {item.get('status') or '—'}" for item in status.get("certificate_status") or [])
        lines.extend(f"Interfaz {item.get('interface')}: {item.get('address')}/{item.get('prefix_length')}" for item in interfaces)
        self.server_status.set_text("\n".join(lines))

    def _server_status_failed(self, error: Exception, generation: int | None = None) -> None:
        if generation is not None and generation != self._server_status_refresh_generation:
            return
        self.server_status.set_text("No se pudo consultar el estado del servidor: " + str(error))

    def _show_repositories_page(self) -> None:
        self._repository_page_generation = getattr(self, "_repository_page_generation", 0) + 1
        self._repository_window_page_generation = self._page_generation
        self.page_description.set_text("Estado de los repositorios de archivos remotos y S3 disponibles para las operaciones.")

        def add_group(title: str, description: str = "") -> Adw.PreferencesGroup:
            group = Adw.PreferencesGroup(title=title, description=description)
            self.page_body.append(group)
            return group

        def add_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget, subtitle: str = "") -> Adw.ActionRow:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.add_suffix(widget)
            row.set_activatable_widget(widget)
            group.add(row)
            return row

        def add_action(group: Adw.PreferencesGroup, title: str, label: str, callback: Any, subtitle: str = "") -> Gtk.Button:
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            add_row(group, title, button, subtitle)
            return button

        status_group = add_group("Estado de los repositorios")
        self.repositories_summary = Gtk.Label(label="Consultando repositorios…", xalign=0)
        self.repositories_summary.set_wrap(True)
        self.repositories_summary.set_selectable(True)
        add_row(status_group, "Inventario remoto", self.repositories_summary)
        add_action(status_group, "Actualizar inventario", "Actualizar repositorios", self._refresh_repositories)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.repositories_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.repositories_grid)
        self.page_body.append(scroller)

        p2v_group = add_group(
            "Compatibilidad P2V heredada",
            "Importa bundles QCOW2 heredados desde un repositorio de archivos; exporta bundles heredados desde S3.",
        )
        self.p2v_import_repository = Gtk.DropDown.new_from_strings(["Repositorio local"])
        add_row(p2v_group, "Repositorio de origen para importar", self.p2v_import_repository)
        self.p2v_source_image_id = Gtk.Entry()
        self.p2v_source_image_id.set_placeholder_text("Identificador QCOW2 heredado")
        add_row(p2v_group, "Imagen QCOW2 de origen", self.p2v_source_image_id)
        self.p2v_import_image_id = Gtk.Entry()
        self.p2v_import_image_id.set_placeholder_text("Nuevo identificador de imagen Feclora")
        add_row(p2v_group, "Nuevo identificador Feclora", self.p2v_import_image_id)
        add_action(p2v_group, "Importación", "Importar bundle P2V heredado", self._import_legacy_p2v)
        self.p2v_export_repository = Gtk.DropDown.new_from_strings(["Selecciona repositorio S3…"])
        add_row(p2v_group, "Repositorio S3 de origen para exportar", self.p2v_export_repository)
        self.p2v_export_image_id = Gtk.Entry()
        self.p2v_export_image_id.set_placeholder_text("Identificador QCOW2 heredado")
        add_row(p2v_group, "Imagen QCOW2 que exportar", self.p2v_export_image_id)
        self.p2v_export_destination = Gtk.DropDown.new_from_strings(["Repositorio local"])
        add_row(p2v_group, "Destino (opcional; vacío = repositorio local)", self.p2v_export_destination)
        add_action(p2v_group, "Exportación", "Exportar bundle P2V desde S3", self._export_legacy_p2v)
        self.p2v_result = Gtk.Label(label="", xalign=0)
        self.p2v_result.set_wrap(True)
        self.p2v_result.set_selectable(True)
        add_row(p2v_group, "Resultado P2V", self.p2v_result)
        pending_p2v_operation = getattr(self, "_latest_p2v_operation_id", None)
        if pending_p2v_operation:
            self.p2v_result.set_text("Recuperando seguimiento P2V " + pending_p2v_operation + "…")
            GLib.idle_add(
                lambda: self._poll_p2v_operation(
                    pending_p2v_operation, self._repository_page_generation,
                    self._repository_window_page_generation,
                ) or GLib.SOURCE_REMOVE
            )

        management_group = add_group("Gestión de repositorios", "Comprobar, montar, desmontar, editar o eliminar definiciones existentes.")
        self.repository_management = Gtk.DropDown.new_from_strings(["Actualiza para seleccionar…"])
        add_row(management_group, "Repositorio", self.repository_management)
        self.repository_action = Gtk.DropDown.new_from_strings(["Comprobar", "Montar", "Desmontar", "Eliminar", "Editar definición"])
        add_row(management_group, "Acción", self.repository_action)
        self.repository_confirmation = Gtk.Entry()
        self.repository_confirmation.set_placeholder_text("Para eliminar: REMOVE identificador")
        add_row(management_group, "Confirmación de eliminación", self.repository_confirmation)
        add_action(management_group, "Aplicar", "Ejecutar acción de repositorio", self._run_repository_action)

        remote_group = add_group("Repositorios SSHFS, NFS y SMB/CIFS", "Las claves SSH, known_hosts y credenciales SMB se seleccionan desde credenciales protegidas.")
        self.remote_id = Gtk.Entry()
        self.remote_id.set_placeholder_text("ID: minúsculas, números y guiones")
        add_row(remote_group, "Identificador", self.remote_id)
        self.remote_provider = Gtk.DropDown.new_from_strings(["SSHFS", "NFS", "SMB/CIFS"])
        self.remote_provider.connect("notify::selected", self._remote_provider_changed)
        add_row(remote_group, "Proveedor", self.remote_provider)
        self.remote_host = Gtk.Entry()
        self.remote_host.set_placeholder_text("Servidor o dirección")
        add_row(remote_group, "Servidor", self.remote_host)
        self.remote_path = Gtk.Entry()
        self.remote_path.set_placeholder_text("Ruta exportada NFS, recurso SMB o ruta SSHFS")
        add_row(remote_group, "Ruta o recurso exportado", self.remote_path)
        self.remote_username = Gtk.Entry()
        self.remote_username.set_placeholder_text("Usuario SSH/SMB")
        add_row(remote_group, "Usuario", self.remote_username)
        self.remote_identity = Gtk.DropDown.new_from_strings(["Selecciona clave SSH…"])
        add_row(remote_group, "Clave SSH protegida", self.remote_identity)
        self.remote_known_hosts = Gtk.DropDown.new_from_strings(["Selecciona known_hosts…"])
        add_row(remote_group, "Known hosts protegido", self.remote_known_hosts)
        self.remote_credential = Gtk.DropDown.new_from_strings(["Selecciona credencial SMB…"])
        add_row(remote_group, "Credencial SMB protegida", self.remote_credential)
        self.remote_port = Gtk.Entry()
        self.remote_port.set_placeholder_text("Puerto SSH/SMB (opcional)")
        add_row(remote_group, "Puerto", self.remote_port)
        self.remote_read_only = Gtk.CheckButton(label="Montar solo lectura")
        add_row(remote_group, "Modo de montaje", self.remote_read_only)
        add_action(remote_group, "Guardar definición", "Guardar definición SSHFS", self._save_ssh_repository)

        s3_group = add_group("Repositorios S3", "La autenticación se referencia mediante una credencial S3 previamente importada; no se introduce ningún secreto aquí.")
        self.s3_id = Gtk.Entry()
        self.s3_id.set_placeholder_text("ID del repositorio S3")
        add_row(s3_group, "Identificador", self.s3_id)
        self.s3_endpoint = Gtk.Entry()
        self.s3_endpoint.set_placeholder_text("Endpoint URL (opcional)")
        add_row(s3_group, "Endpoint", self.s3_endpoint)
        self.s3_region = Gtk.Entry()
        self.s3_region.set_placeholder_text("Región")
        add_row(s3_group, "Región", self.s3_region)
        self.s3_bucket = Gtk.Entry()
        self.s3_bucket.set_placeholder_text("Bucket")
        add_row(s3_group, "Bucket", self.s3_bucket)
        self.s3_prefix = Gtk.Entry()
        self.s3_prefix.set_placeholder_text("Prefijo (opcional)")
        add_row(s3_group, "Prefijo", self.s3_prefix)
        self.s3_credential = Gtk.DropDown.new_from_strings(["Selecciona credencial S3…"] )
        add_row(s3_group, "Credencial S3", self.s3_credential)
        self.s3_read_only = Gtk.CheckButton(label="Repositorio S3 solo lectura")
        add_row(s3_group, "Permisos", self.s3_read_only)
        add_action(s3_group, "Guardar definición", "Guardar definición S3", self._save_s3_repository)

        credential_group = add_group("Credenciales systemd cifradas", "Importa archivos de credenciales protegidos y administra su ciclo de vida.")
        self.credential_id = Gtk.Entry()
        self.credential_id.set_placeholder_text("ID de credencial")
        add_row(credential_group, "Identificador", self.credential_id)
        self.credential_kind = Gtk.DropDown.new_from_strings(["s3", "smb", "ssh-key", "known-hosts"])
        add_row(credential_group, "Tipo de credencial", self.credential_kind)
        self.credential_source = Gtk.Entry()
        self.credential_source.set_placeholder_text("Ruta del archivo fuente protegido")
        add_row(credential_group, "Archivo fuente", self.credential_source)
        self.credential_replace = Gtk.CheckButton(label="Reemplazar credencial existente")
        add_row(credential_group, "Sustitución", self.credential_replace)
        add_action(credential_group, "Importar", "Importar credencial", self._import_repository_credential)
        self.credential_management = Gtk.DropDown.new_from_strings(["Actualiza para seleccionar…"])
        add_row(credential_group, "Credencial instalada", self.credential_management)
        self.credential_confirmation = Gtk.Entry()
        self.credential_confirmation.set_placeholder_text("Para eliminar: REMOVE identificador")
        add_row(credential_group, "Confirmación de eliminación", self.credential_confirmation)
        add_action(credential_group, "Eliminar", "Eliminar credencial no referenciada", self._remove_repository_credential)
        self.repository_action_result = Gtk.Label(label="", xalign=0)
        self.repository_action_result.set_wrap(True)
        self.repository_action_result.set_selectable(True)
        add_row(credential_group, "Resultado", self.repository_action_result)

        self._remote_provider_changed(self.remote_provider)
        self._refresh_repositories(None)

    def _refresh_repositories(self, _button: Gtk.Button | None) -> None:
        self._repository_refresh_generation = getattr(self, "_repository_refresh_generation", 0) + 1
        generation = self._repository_refresh_generation
        page_generation = self._repository_page_generation
        window_generation = self._repository_window_page_generation
        self._repository_refresh_pending_parts = {"remote", "s3"}
        self._repository_refresh_failed = False
        self.repositories_summary.set_text("Consultando repositorios de archivos y S3…")
        self.api.submit(
            "remote_repositories",
            on_success=lambda response: self._populate_remote_repositories(response, refresh_generation=generation)
            if page_generation == self._repository_page_generation and window_generation == self._page_generation and generation == self._repository_refresh_generation else None,
            on_error=lambda error: self._repository_refresh_part_failed("remote", error, generation)
            if page_generation == self._repository_page_generation and generation == self._repository_refresh_generation else None,
        )
        self.api.submit(
            "s3_repositories",
            on_success=lambda response: self._populate_s3_repositories(response, refresh_generation=generation)
            if page_generation == self._repository_page_generation and generation == self._repository_refresh_generation else None,
            on_error=lambda error: self._repository_refresh_part_failed("s3", error, generation)
            if page_generation == self._repository_page_generation and generation == self._repository_refresh_generation else None,
        )
        self.api.submit(
            "systemd_credentials",
            on_success=lambda response: self._populate_repository_credentials(response)
            if page_generation == self._repository_page_generation and generation == self._repository_refresh_generation else None,
            on_error=lambda error: self._repositories_failed(error)
            if page_generation == self._repository_page_generation and generation == self._repository_refresh_generation else None,
        )

    def _repository_refresh_part_loaded(self, part: str, generation: int) -> None:
        if generation != self._repository_refresh_generation:
            return
        pending = getattr(self, "_repository_refresh_pending_parts", set())
        pending.discard(part)
        if not pending and not getattr(self, "_repository_refresh_failed", False):
            self._render_repositories()

    def _repository_refresh_part_failed(self, part: str, error: Exception, generation: int) -> None:
        if generation != self._repository_refresh_generation:
            return
        self._repository_refresh_failed = True
        pending = getattr(self, "_repository_refresh_pending_parts", set())
        pending.discard(part)
        self._repositories_failed(error)

    def _populate_remote_repositories(
        self, response: dict[str, Any], *, refresh_generation: int | None = None
    ) -> None:
        self.remote_repository_rows = [("NFS/SSH", item) for item in response.get("repositories", []) if isinstance(item, dict)]
        if hasattr(self, "p2v_import_repository"):
            usable = [item for item in self.remote_repository_rows if item[1].get("mounted") and item[1].get("verified") and not item[1].get("read_only")]
            self.p2v_import_repositories = usable
            labels = ["Repositorio local"] + [str(item.get("id")) for _, item in usable]
            self.p2v_import_repository.set_model(Gtk.StringList.new(labels))
            self.p2v_export_destinations = usable
            self.p2v_export_destination.set_model(Gtk.StringList.new(["Repositorio local"] + [str(item.get("id")) for _, item in usable]))
        if refresh_generation is None:
            self._render_repositories()
        else:
            self._repository_refresh_part_loaded("remote", refresh_generation)

    def _populate_s3_repositories(
        self, response: dict[str, Any], *, refresh_generation: int | None = None
    ) -> None:
        self.s3_repository_rows = [("S3", item) for item in response.get("repositories", []) if isinstance(item, dict)]
        if hasattr(self, "p2v_export_repository"):
            usable = [item for _, item in self.s3_repository_rows]
            self.p2v_export_repositories = usable
            labels = ["Selecciona repositorio S3…"] + [str(item.get("id")) for item in usable]
            self.p2v_export_repository.set_model(Gtk.StringList.new(labels))
            self.p2v_export_repository.set_selected(0)
        if refresh_generation is None:
            self._render_repositories()
        else:
            self._repository_refresh_part_loaded("s3", refresh_generation)

    def _import_legacy_p2v(self, _button: Gtk.Button) -> None:
        import re
        source_image_id = self.p2v_source_image_id.get_text().strip()
        image_id = self.p2v_import_image_id.get_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", source_image_id) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
            self.p2v_result.set_text("Indica identificadores válidos para la imagen QCOW2 de origen y la nueva imagen.")
            return
        params = {"source_image_id": source_image_id, "image_id": image_id}
        selected = self.p2v_import_repository.get_selected()
        repositories = getattr(self, "p2v_import_repositories", [])
        if selected:
            if selected - 1 >= len(repositories):
                self.p2v_result.set_text("Selecciona un repositorio de archivos válido.")
                return
            params["repository_id"] = repositories[selected - 1][1]["id"]
        self.p2v_result.set_text("Solicitando importación P2V…")
        self._submit_p2v_operation("import_p2v", params)

    def _export_legacy_p2v(self, _button: Gtk.Button) -> None:
        import re
        image_id = self.p2v_export_image_id.get_text().strip()
        source_index = self.p2v_export_repository.get_selected()
        sources = getattr(self, "p2v_export_repositories", [])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
            self.p2v_result.set_text("Indica un identificador QCOW2 heredado válido.")
            return
        if source_index == 0 or source_index - 1 >= len(sources):
            self.p2v_result.set_text("Selecciona un repositorio S3 de origen escribible.")
            return
        params = {"image_id": image_id, "source_repository_id": sources[source_index - 1]["id"]}
        destination_index = self.p2v_export_destination.get_selected()
        destinations = getattr(self, "p2v_export_destinations", [])
        if destination_index:
            if destination_index - 1 >= len(destinations):
                self.p2v_result.set_text("Selecciona un repositorio de destino válido.")
                return
            params["destination_repository_id"] = destinations[destination_index - 1][1]["id"]
        self.p2v_result.set_text("Solicitando exportación P2V desde S3…")
        self._submit_p2v_operation("export_p2v_s3", params)

    def _submit_p2v_operation(self, action: str, params: dict[str, Any]) -> None:
        self._p2v_action_generation = getattr(self, "_p2v_action_generation", 0) + 1
        request_generation = self._p2v_action_generation
        page_generation = self._repository_page_generation
        window_generation = self._repository_window_page_generation
        self.api.submit(
            action, params,
            on_success=lambda result: self._p2v_operation_accepted(result, page_generation, window_generation, request_generation),
            on_error=lambda error: self._p2v_operation_failed(error, page_generation, window_generation, request_generation),
        )

    def _p2v_operation_accepted(
        self, result: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None, request_generation: int | None = None,
    ) -> None:
        operation_id = result.get("operation_id")
        self._p2v_operation_results = getattr(self, "_p2v_operation_results", {})
        if isinstance(operation_id, str) and operation_id:
            self._p2v_operation_results[operation_id] = result
        if not isinstance(operation_id, str) or not operation_id:
            self._p2v_operation_failed(RuntimeError("El backend no devolvió operation_id."), page_generation, window_generation, request_generation)
            return
        if request_generation == self._p2v_action_generation:
            self._latest_p2v_operation_id = operation_id
        if page_generation != self._repository_page_generation or window_generation != self._page_generation or request_generation != self._p2v_action_generation:
            return
        self.p2v_result.set_text("Operación P2V aceptada: " + operation_id + ". Consultando progreso…")
        GLib.timeout_add_seconds(
            1, lambda: self._poll_p2v_operation(operation_id, page_generation, window_generation)
        )

    def _p2v_view_is_current(self, page_generation: int, window_generation: int, operation_id: str) -> bool:
        return (
            page_generation == self._repository_page_generation
            and window_generation == self._page_generation
            and operation_id == getattr(self, "_latest_p2v_operation_id", None)
        )

    def _poll_p2v_operation(self, operation_id: str, page_generation: int, window_generation: int) -> bool:
        self.api.submit(
            "local_operation_status", {"operation_id": operation_id},
            on_success=lambda status: self._p2v_operation_status_loaded(status, operation_id, page_generation, window_generation),
            on_error=lambda error: self._p2v_operation_status_failed(error, operation_id, page_generation, window_generation),
        )
        return GLib.SOURCE_REMOVE

    def _p2v_operation_status_loaded(
        self, status: dict[str, Any], operation_id: str,
        page_generation: int, window_generation: int,
    ) -> None:
        self._p2v_operation_results = getattr(self, "_p2v_operation_results", {})
        self._p2v_operation_results.setdefault(operation_id, {})["status"] = status
        if not self._p2v_view_is_current(page_generation, window_generation, operation_id):
            return
        if status.get("operation_id") not in (None, operation_id):
            self._p2v_operation_errors = getattr(self, "_p2v_operation_errors", {})
            self._p2v_operation_errors[operation_id] = "El estado devuelto pertenece a otra operación."
            return
        state = status.get("state", "unknown")
        events = status.get("events") or []
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            details = events[-1].get("details", {}) if events else {}
            detail = details.get("error") or details.get("reason") or details
            self.p2v_result.set_text(f"Operación P2V {state}: {detail}")
            if state == "completed":
                self._refresh_repositories(None)
            return
        self.p2v_result.set_text(f"Operación P2V {operation_id}: {state}.")
        GLib.timeout_add_seconds(
            2, lambda: self._poll_p2v_operation(operation_id, page_generation, window_generation)
        )

    def _p2v_operation_status_failed(
        self, error: Exception, operation_id: str,
        page_generation: int, window_generation: int,
    ) -> None:
        self._p2v_operation_errors = getattr(self, "_p2v_operation_errors", {})
        self._p2v_operation_errors[operation_id] = "status: " + str(error)
        if not self._p2v_view_is_current(page_generation, window_generation, operation_id):
            return
        self.p2v_result.set_text("No se pudo consultar el progreso P2V; se conserva el ID " + operation_id + ": " + str(error))
        GLib.timeout_add_seconds(
            5, lambda: self._poll_p2v_operation(operation_id, page_generation, window_generation)
        )

    def _p2v_operation_failed(
        self, error: Exception, page_generation: int | None = None,
        window_generation: int | None = None, request_generation: int | None = None,
    ) -> None:
        self._p2v_operation_errors = getattr(self, "_p2v_operation_errors", [])
        self._p2v_operation_errors.append(str(error))
        if page_generation != self._repository_page_generation or window_generation != self._page_generation or request_generation != self._p2v_action_generation:
            return
        self.p2v_result.set_text("No se pudo iniciar la operación P2V: " + str(error))

    def _populate_repository_credentials(self, response: dict[str, Any]) -> None:
        self.repository_credentials = [item for item in response.get("credentials", []) if isinstance(item, dict)]
        labels = ["Selecciona credencial…"] + [
            f"{item.get('kind')}:{item.get('id')}" for item in self.repository_credentials
        ]
        self.credential_management.set_model(Gtk.StringList.new(labels))
        self.credential_management.set_selected(0)
        self._populate_remote_credential_selector("ssh-key", self.remote_identity)
        self._populate_remote_credential_selector("known-hosts", self.remote_known_hosts)
        self._populate_remote_credential_selector("smb", self.remote_credential)
        self._populate_s3_credential_selector()

    def _populate_s3_credential_selector(self) -> None:
        previous_id = self._selected_s3_credential_id()
        self._s3_credentials = [
            item for item in getattr(self, "repository_credentials", [])
            if item.get("kind") == "s3" and item.get("path")
        ]
        self.s3_credential.set_model(Gtk.StringList.new(
            ["Selecciona credencial S3…"] + [str(item.get("id")) for item in self._s3_credentials]
        ))
        selected = next(
            (index + 1 for index, item in enumerate(self._s3_credentials) if item.get("id") == previous_id),
            0,
        )
        self.s3_credential.set_selected(selected)

    def _selected_s3_credential_id(self) -> str | None:
        selected = self.s3_credential.get_selected()
        credentials = getattr(self, "_s3_credentials", [])
        if selected == 0 or selected - 1 >= len(credentials):
            return None
        identifier = credentials[selected - 1].get("id")
        return identifier if isinstance(identifier, str) and identifier else None

    def _populate_remote_credential_selector(self, kind: str, selector: Gtk.DropDown) -> None:
        attribute = f"_remote_{kind.replace('-', '_')}_credentials"
        previous = getattr(self, attribute, [])
        selected_index = selector.get_selected()
        previous_path = (
            previous[selected_index - 1].get("path")
            if selected_index > 0 and selected_index - 1 < len(previous) else None
        )
        credentials = [
            item for item in getattr(self, "repository_credentials", [])
            if item.get("kind") == kind and item.get("path")
        ]
        setattr(self, attribute, credentials)
        selector.set_model(Gtk.StringList.new(
            ["Selecciona credencial…"] + [str(item.get("id")) for item in credentials]
        ))
        selected = next(
            (index + 1 for index, item in enumerate(credentials) if item.get("path") == previous_path),
            0,
        )
        selector.set_selected(selected)

    def _remote_provider_changed(self, _widget: Gtk.DropDown, _pspec: Any = None) -> None:
        provider = ("sshfs", "nfs", "smb")[min(self.remote_provider.get_selected(), 2)]
        self.remote_username.set_visible(provider in {"sshfs", "smb"})
        self.remote_identity.set_visible(provider == "sshfs")
        self.remote_known_hosts.set_visible(provider == "sshfs")
        self.remote_credential.set_visible(provider == "smb")
        self.remote_port.set_visible(provider in {"sshfs", "smb"})

    def _submit_repository_action(self, action: str, params: dict[str, Any]) -> None:
        self._repository_action_generation = getattr(self, "_repository_action_generation", 0) + 1
        request_generation = self._repository_action_generation
        page_generation = self._repository_page_generation
        window_generation = self._repository_window_page_generation
        self.api.submit(
            action, params,
            on_success=lambda response: self._repository_action_done(response, page_generation, window_generation, request_generation),
            on_error=lambda error: self._repository_action_failed(error, page_generation, window_generation, request_generation),
        )

    def _repository_action_done(
        self, response: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None, request_generation: int | None = None,
    ) -> None:
        self._repository_action_results = getattr(self, "_repository_action_results", [])
        self._repository_action_results.append(response)
        if page_generation != self._repository_page_generation or window_generation != self._page_generation or request_generation != self._repository_action_generation:
            return
        self.repository_action_result.set_text("Acción completada: " + str(response))
        self.repository_confirmation.set_text("")
        self.remote_id.set_editable(True)
        self.s3_id.set_editable(True)
        self._refresh_repositories(None)

    def _repository_action_failed(
        self, error: Exception, page_generation: int | None = None,
        window_generation: int | None = None, request_generation: int | None = None,
    ) -> None:
        self._repository_action_errors = getattr(self, "_repository_action_errors", [])
        self._repository_action_errors.append(str(error))
        if page_generation != self._repository_page_generation or window_generation != self._page_generation or request_generation != self._repository_action_generation:
            return
        self.repository_action_result.set_text("La operación de repositorio falló: " + str(error))

    def _run_repository_action(self, _button: Gtk.Button) -> None:
        selected = self.repository_management.get_selected()
        rows = getattr(self, "repository_management_rows", [])
        if selected == 0 or selected - 1 >= len(rows):
            self.repository_action_result.set_text("Selecciona un repositorio.")
            return
        kind, item = rows[selected - 1]
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            self.repository_action_result.set_text("El repositorio seleccionado no tiene un ID válido.")
            return
        actions = ("check", "mount", "unmount", "remove", "edit")
        index = self.repository_action.get_selected()
        if index >= len(actions):
            self.repository_action_result.set_text("Selecciona una acción válida.")
            return
        action = actions[index]
        if action == "edit":
            if kind == "S3":
                self.s3_id.set_text(identifier)
                self.s3_id.set_editable(False)
                self.s3_endpoint.set_text(item.get("endpoint_url") or "")
                self.s3_region.set_text(item.get("region") or "")
                self.s3_bucket.set_text(item.get("bucket") or "")
                self.s3_prefix.set_text(item.get("prefix") or "")
                self.s3_credential.set_selected(next((index + 1 for index, credential in enumerate(getattr(self, "_s3_credentials", [])) if credential.get("id") == item.get("credential_id")), 0))
                self.s3_read_only.set_active(bool(item.get("read_only")))
                self.repository_action_result.set_text("Definición S3 cargada; guarda los cambios en el formulario S3.")
                return
            if item.get("mount_state") != "unmounted":
                self.repository_action_result.set_text("Desmonta y verifica el estado unmounted antes de editar.")
                return
            provider = item.get("provider")
            provider_index = {"sshfs": 0, "nfs": 1, "smb": 2}.get(provider)
            if provider_index is None:
                self.repository_action_result.set_text("Proveedor de repositorio no reconocido.")
                return
            self.remote_id.set_text(identifier)
            self.remote_id.set_editable(False)
            self.remote_provider.set_selected(provider_index)
            self.remote_host.set_text(item.get("host") or "")
            self.remote_path.set_text(item.get("remote_path") or "")
            self.remote_username.set_text(item.get("username") or "")
            self._select_remote_credential(self.remote_identity, "_remote_ssh_key_credentials", item.get("identity_file"))
            self._select_remote_credential(self.remote_known_hosts, "_remote_known_hosts_credentials", item.get("known_hosts_file"))
            self._select_remote_credential(self.remote_credential, "_remote_smb_credentials", item.get("credential_file"))
            self.remote_port.set_text(str(item.get("port") or ""))
            self.remote_read_only.set_active(bool(item.get("read_only")))
            self._remote_provider_changed(self.remote_provider)
            self.repository_action_result.set_text(f"Definición {provider} cargada; guarda los cambios en el formulario.")
            return
        if kind == "S3":
            api_action = {"check": "check_s3_repository", "remove": "remove_s3_repository"}.get(action)
            if api_action is None:
                self.repository_action_result.set_text("S3 solo admite comprobar o eliminar su definición.")
                return
        else:
            api_action = {
                "check": "check_remote_repository", "mount": "mount_remote_repository",
                "unmount": "unmount_remote_repository", "remove": "remove_remote_repository",
            }[action]
            mount_state = item.get("mount_state")
            if action in {"mount", "remove"} and mount_state != "unmounted":
                self.repository_action_result.set_text("La acción requiere que el estado de montaje sea unmounted.")
                return
            if action == "unmount" and mount_state != "identity_verified":
                self.repository_action_result.set_text("Solo se desmonta un repositorio con identidad de montaje verificada.")
                return
        if action == "remove" and self.repository_confirmation.get_text().strip() != f"REMOVE {identifier}":
            self.repository_action_result.set_text(f"Para eliminar escribe exactamente: REMOVE {identifier}")
            return
        self.repository_action_result.set_text(f"Ejecutando {api_action} para {identifier}…")
        self._submit_repository_action(api_action, {"id": identifier})

    def _save_ssh_repository(self, _button: Gtk.Button) -> None:
        import re
        identifier = self.remote_id.get_text().strip()
        host = self.remote_host.get_text().strip()
        remote_path = self.remote_path.get_text().strip()
        providers = ("sshfs", "nfs", "smb")
        provider_index = self.remote_provider.get_selected()
        provider = providers[provider_index] if provider_index < len(providers) else ""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", identifier) or not host or not remote_path:
            self.repository_action_result.set_text("ID inválido; servidor y ruta remota son obligatorios.")
            return
        port_text = self.remote_port.get_text().strip()
        try:
            port = int(port_text) if port_text and provider in {"sshfs", "smb"} else None
        except ValueError:
            self.repository_action_result.set_text("El puerto debe ser un entero.")
            return
        if port is not None and not 1 <= port <= 65535:
            self.repository_action_result.set_text("El puerto debe estar entre 1 y 65535.")
            return
        username = self.remote_username.get_text().strip() or None if provider in {"sshfs", "smb"} else None
        identity_file = self._selected_remote_credential_path(self.remote_identity, "_remote_ssh_key_credentials") if provider == "sshfs" else None
        known_hosts_file = self._selected_remote_credential_path(self.remote_known_hosts, "_remote_known_hosts_credentials") if provider == "sshfs" else None
        credential_file = self._selected_remote_credential_path(self.remote_credential, "_remote_smb_credentials") if provider == "smb" else None
        if provider == "sshfs" and (not username or not identity_file or not known_hosts_file):
            self.repository_action_result.set_text("SSHFS requiere usuario, clave privada y known_hosts protegidos.")
            return
        if provider == "smb" and (not username or not credential_file):
            self.repository_action_result.set_text("SMB/CIFS requiere usuario y credencial cifrada.")
            return
        params = {
            "id": identifier, "provider": provider, "host": host, "remote_path": remote_path,
            "username": username, "credential_file": credential_file,
            "identity_file": identity_file, "known_hosts_file": known_hosts_file,
            "port": port, "read_only": self.remote_read_only.get_active(),
        }
        existing = next((item for _, item in getattr(self, "remote_repository_rows", []) if item.get("id") == identifier), None)
        if existing and existing.get("mount_state") != "unmounted":
            self.repository_action_result.set_text("No se puede editar una definición montada; desmonta primero.")
            return
        action = "update_remote_repository" if existing else "add_remote_repository"
        self.repository_action_result.set_text(f"Guardando definición {provider.upper()}…")
        self._submit_repository_action(action, params)

    def _select_remote_credential(self, selector: Gtk.DropDown, attribute: str, path: Any) -> None:
        credentials = getattr(self, attribute, [])
        index = next((i for i, item in enumerate(credentials) if item.get("path") == path), -1)
        selector.set_selected(index + 1 if index >= 0 else 0)

    def _selected_remote_credential_path(self, selector: Gtk.DropDown, attribute: str) -> str | None:
        credentials = getattr(self, attribute, [])
        selected = selector.get_selected()
        if selected == 0 or selected - 1 >= len(credentials):
            return None
        path = credentials[selected - 1].get("path")
        return path if isinstance(path, str) and path else None

    def _save_s3_repository(self, _button: Gtk.Button) -> None:
        import re
        identifier = self.s3_id.get_text().strip()
        region = self.s3_region.get_text().strip()
        bucket = self.s3_bucket.get_text().strip()
        credential_id = self._selected_s3_credential_id()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", identifier) or not region or not bucket or not credential_id:

            self.repository_action_result.set_text("ID, región, bucket y credencial S3 son obligatorios y deben ser válidos.")
            return
        params = {
            "id": identifier, "endpoint_url": self.s3_endpoint.get_text().strip() or None,
            "region": region, "bucket": bucket, "prefix": self.s3_prefix.get_text().strip(),
            "credential_id": credential_id, "read_only": self.s3_read_only.get_active(),
        }
        existing = next((item for _, item in getattr(self, "s3_repository_rows", []) if item.get("id") == identifier), None)
        action = "update_s3_repository" if existing else "add_s3_repository"
        self.repository_action_result.set_text("Guardando definición S3…")
        self._submit_repository_action(action, params)

    def _import_repository_credential(self, _button: Gtk.Button) -> None:
        import re
        identifier = self.credential_id.get_text().strip()
        source_file = self.credential_source.get_text().strip()
        kinds = ("s3", "smb", "ssh-key", "known-hosts")
        selected = self.credential_kind.get_selected()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", identifier) or not source_file or selected >= len(kinds):
            self.repository_action_result.set_text("Indica un ID válido, tipo y ruta del archivo fuente.")
            return
        params = {
            "id": identifier, "kind": kinds[selected], "source_file": source_file,
            "replace": self.credential_replace.get_active(),
        }
        self.repository_action_result.set_text("Importando credencial cifrada…")
        self._submit_repository_action("put_systemd_credential", params)

    def _remove_repository_credential(self, _button: Gtk.Button) -> None:
        selected = self.credential_management.get_selected()
        credentials = getattr(self, "repository_credentials", [])
        if selected == 0 or selected - 1 >= len(credentials):
            self.repository_action_result.set_text("Selecciona una credencial.")
            return
        item = credentials[selected - 1]
        identifier, kind = item.get("id"), item.get("kind")
        if not isinstance(identifier, str) or not isinstance(kind, str):
            self.repository_action_result.set_text("La credencial seleccionada no es válida.")
            return
        if self.credential_confirmation.get_text().strip() != f"REMOVE {identifier}":
            self.repository_action_result.set_text(f"Para eliminar escribe exactamente: REMOVE {identifier}")
            return
        self.repository_action_result.set_text("Eliminando credencial; el backend comprobará que no esté referenciada…")
        self._submit_repository_action("remove_systemd_credential", {"id": identifier, "kind": kind})

    def _render_repositories(self) -> None:
        if not hasattr(self, "repositories_grid"):
            return
        previous_key = None
        if hasattr(self, "repository_management"):
            previous_index = self.repository_management.get_selected()
            previous_rows = getattr(self, "repository_management_rows", [])
            if 0 < previous_index <= len(previous_rows):
                previous_kind, previous_item = previous_rows[previous_index - 1]
                previous_key = (previous_kind, previous_item.get("id"))
        rows = getattr(self, "remote_repository_rows", []) + getattr(self, "s3_repository_rows", [])
        self.repository_management_rows = rows
        if hasattr(self, "repository_management"):
            labels = ["Selecciona repositorio…"] + [
                f"{kind}: {item.get('id')}" for kind, item in rows
            ]
            self.repository_management.set_model(Gtk.StringList.new(labels))
            selected_index = next(
                (index + 1 for index, (kind, item) in enumerate(rows)
                 if (kind, item.get("id")) == previous_key),
                0,
            )
            self.repository_management.set_selected(selected_index)
        grid = self.repositories_grid
        while child := grid.get_first_child():
            grid.remove(child)
        for column, heading in enumerate(("Tipo", "Identificador", "Nombre", "Estado", "Montado", "Verificado", "Solo lectura")):
            label = Gtk.Label(label=heading, xalign=0)
            label.add_css_class("heading")
            grid.attach(label, column, 0, 1, 1)
        for row, (kind, item) in enumerate(rows, start=1):
            values = (
                kind, item.get("id") or item.get("repository_id") or "—",
                item.get("name") or item.get("id") or "—",
                item.get("state") or item.get("status") or "—",
                "sí" if item.get("mounted") else "no",
                "sí" if item.get("verified") else "no",
                "sí" if item.get("read_only") else "no",
            )
            for column, value in enumerate(values):
                label = Gtk.Label(label=str(value), xalign=0)
                label.set_selectable(True)
                grid.attach(label, column, row, 1, 1)
        self.repositories_summary.set_text(f"Repositorios disponibles: {len(rows)}")

    def _repositories_failed(self, error: Exception) -> None:
        self.repositories_summary.set_text("No se pudieron consultar los repositorios: " + str(error))

    def _show_remote_jobs_page(self) -> None:
        self._remote_jobs_page_generation = getattr(self, "_remote_jobs_page_generation", 0) + 1
        page_generation = self._remote_jobs_page_generation
        def render(item: dict[str, Any]) -> tuple[str, ...]:
            clients = item.get("clients") or {}
            return (
                item.get("job_id") or "—", item.get("operation") or "—",
                item.get("source_device") if item.get("operation") == "clone" else item.get("image_id") or "—",
                item.get("target_type") or "—", item.get("transport") or "—",
                item.get("job_state") or "—",
                ", ".join(f"{mac}: {state.get('state', '—')}" for mac, state in clients.items()) or "No conectados",
                item.get("event_count") or 0,
            )
        self._history_page("Trabajos remotos persistidos y estado de sus clientes.", ("ID", "Operación", "Imagen/origen", "Destino", "Transporte", "Estado", "Clientes", "Eventos"), "deployment_jobs", "jobs", render)
        title = Gtk.Label(label="Crear / importar definición de trabajo", xalign=0)
        title.add_css_class("heading")
        self.page_body.append(title)
        self.remote_job_json = Gtk.TextView()
        self.remote_job_json.set_monospace(True)
        self.remote_job_json.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.remote_job_json.set_size_request(-1, 180)
        self.page_body.append(self.remote_job_json)
        create_group = Adw.PreferencesGroup(title="Definición del trabajo")
        self.page_body.append(create_group)
        create = Gtk.Button(label="Validar y guardar definición JSON")
        create.connect("clicked", self._create_remote_job)
        create_row = Adw.ActionRow(title="Guardar definición", subtitle="Valida el JSON antes de persistirlo")
        create_row.add_suffix(create)
        create_row.set_activatable_widget(create)
        create_group.add(create_row)
        import_group = Adw.PreferencesGroup(title="Importar definición")
        self.page_body.append(import_group)
        self.remote_import_source = Gtk.DropDown.new_from_strings(["Archivo local", "URL HTTP/HTTPS", "Repositorio montado", "SCP · SSHFS"])
        source_row = Adw.ActionRow(title="Origen de importación")
        source_row.add_suffix(self.remote_import_source)
        source_row.set_activatable_widget(self.remote_import_source)
        import_group.add(source_row)
        self.remote_import_path = Gtk.Entry()
        self.remote_import_path.set_placeholder_text("Ruta local / URL / ruta relativa")
        path_row = Adw.ActionRow(title="Ruta o URL")
        path_row.add_suffix(self.remote_import_path)
        path_row.set_activatable_widget(self.remote_import_path)
        import_group.add(path_row)
        self.remote_import_repository = Gtk.DropDown.new_from_strings(["Selecciona repositorio…"])
        repository_row = Adw.ActionRow(title="Repositorio")
        repository_row.add_suffix(self.remote_import_repository)
        repository_row.set_activatable_widget(self.remote_import_repository)
        import_group.add(repository_row)
        import_job = Gtk.Button(label="Importar y validar definición")
        import_job.connect("clicked", self._import_remote_job)
        import_row = Adw.ActionRow(title="Importar definición")
        import_row.add_suffix(import_job)
        import_row.set_activatable_widget(import_job)
        import_group.add(import_row)
        action_group = Adw.PreferencesGroup(title="Servicio de despliegue")
        self.page_body.append(action_group)
        self.remote_job_select = Gtk.DropDown.new_from_strings(["Actualizando trabajos…"])
        job_row = Adw.ActionRow(title="Trabajo remoto")
        job_row.add_suffix(self.remote_job_select)
        job_row.set_activatable_widget(self.remote_job_select)
        action_group.add(job_row)
        self.remote_job_action = Gtk.DropDown.new_from_strings(["Consultar estado", "Iniciar servicio", "Actualizar estado", "Autorizar trabajo", "Cancelar trabajo", "Detener servicio", "Reconciliar interrumpido"])
        action_row = Adw.ActionRow(title="Acción")
        action_row.add_suffix(self.remote_job_action)
        action_row.set_activatable_widget(self.remote_job_action)
        action_group.add(action_row)
        self.remote_job_confirmation = Gtk.Entry()
        self.remote_job_confirmation.set_placeholder_text("Frase exacta requerida por la acción seleccionada")
        confirmation_row = Adw.ActionRow(title="Confirmación")
        confirmation_row.add_suffix(self.remote_job_confirmation)
        confirmation_row.set_activatable_widget(self.remote_job_confirmation)
        action_group.add(confirmation_row)
        run_action = Gtk.Button(label="Ejecutar acción")
        run_action.connect("clicked", self._run_remote_job_action)
        run_row = Adw.ActionRow(title="Ejecutar")
        run_row.add_suffix(run_action)
        run_row.set_activatable_widget(run_action)
        action_group.add(run_row)
        self.remote_job_result = Gtk.Label(label="Sin acción ejecutada.", xalign=0)
        self.remote_job_result.set_wrap(True)
        self.remote_job_result.set_selectable(True)
        result_row = Adw.ActionRow(title="Resultado")
        result_row.add_suffix(self.remote_job_result)
        action_group.add(result_row)
        self._remote_jobs = []
        self._remote_import_remote_rows = []
        self._remote_import_s3_rows = []
        self._remote_import_pending_parts = {"remote", "s3"}
        self._remote_import_failed = False
        self.api.submit(
            "deployment_jobs",
            on_success=lambda response: self._populate_remote_job_controls(response)
            if page_generation == self._remote_jobs_page_generation else None,
            on_error=lambda error: self._history_failed(error)
            if page_generation == self._remote_jobs_page_generation else None,
        )
        self.api.submit(
            "remote_repositories",
            on_success=lambda response: self._populate_remote_import_repositories(response, page_generation=page_generation)
            if page_generation == self._remote_jobs_page_generation else None,
            on_error=lambda error: self._remote_import_part_failed("remote", error, page_generation)
            if page_generation == self._remote_jobs_page_generation else None,
        )
        self.api.submit(
            "s3_repositories",
            on_success=lambda response: self._populate_remote_import_s3_repositories(response, page_generation=page_generation)
            if page_generation == self._remote_jobs_page_generation else None,
            on_error=lambda error: self._remote_import_part_failed("s3", error, page_generation)
            if page_generation == self._remote_jobs_page_generation else None,
        )

    def _populate_remote_job_controls(self, response: dict[str, Any]) -> None:
        # Keep the backing list and dropdown positions identical: action handlers
        # resolve the selected row by index, so entries without an ID must be excluded.
        self._remote_jobs = [
            item for item in response.get("jobs", [])
            if isinstance(item, dict) and isinstance(item.get("job_id"), str) and item.get("job_id").strip()
        ]
        labels = ["Selecciona trabajo…"] + [
            f"{item.get('job_id')} · {item.get('job_state')}" for item in self._remote_jobs
        ]
        self.remote_job_select.set_model(Gtk.StringList.new(labels))
        self.remote_job_select.set_selected(0)

    def _populate_remote_import_repositories(
        self, response: dict[str, Any], *, page_generation: int | None = None
    ) -> None:
        self._remote_import_remote_rows = [
            item for item in response.get("repositories", [])
            if isinstance(item, dict) and item.get("mounted") and item.get("verified")
        ]
        if page_generation is None:
            self._render_remote_import_repositories()
        else:
            self._remote_import_repository_part_loaded("remote", page_generation)

    def _populate_remote_import_s3_repositories(
        self, response: dict[str, Any], *, page_generation: int | None = None
    ) -> None:
        self._remote_import_s3_rows = [
            item for item in response.get("repositories", [])
            if isinstance(item, dict) and item.get("mounted") and item.get("verified")
        ]
        if page_generation is None:
            self._render_remote_import_repositories()
        else:
            self._remote_import_repository_part_loaded("s3", page_generation)

    def _remote_import_repository_part_loaded(self, part: str, page_generation: int) -> None:
        if page_generation != self._remote_jobs_page_generation:
            return
        pending = getattr(self, "_remote_import_pending_parts", set())
        pending.discard(part)
        if not pending and not getattr(self, "_remote_import_failed", False):
            self._render_remote_import_repositories()

    def _remote_import_part_failed(self, part: str, error: Exception, page_generation: int) -> None:
        if page_generation != self._remote_jobs_page_generation:
            return
        self._remote_import_failed = True
        pending = getattr(self, "_remote_import_pending_parts", set())
        pending.discard(part)
        self._history_failed(error)

    def _render_remote_import_repositories(self) -> None:
        rows = getattr(self, "_remote_import_remote_rows", []) + getattr(self, "_remote_import_s3_rows", [])
        self._remote_import_rows = rows
        self.remote_import_repository.set_model(Gtk.StringList.new(
            ["Selecciona repositorio…"] + [str(item.get("id")) for item in rows]
        ))
        self.remote_import_repository.set_selected(0)

    def _remote_job_json_text(self) -> str:
        buffer = self.remote_job_json.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, True)

    def _create_remote_job(self, _button: Gtk.Button) -> None:
        try:
            job = json.loads(self._remote_job_json_text())
            if not isinstance(job, dict):
                raise ValueError("La definición debe ser un objeto JSON.")
        except (json.JSONDecodeError, ValueError) as error:
            self.remote_job_result.set_text("JSON no válido: " + str(error))
            return
        page_generation = self._remote_jobs_page_generation
        self.remote_job_result.set_text("Validando y guardando definición; no se inicia ningún servicio…")
        self.api.submit(
            "create_deployment_job", {"job": job},
            on_success=lambda result, generation=page_generation: self._remote_job_action_done(
                result, generation, action="create_deployment_job"
            ),
            on_error=lambda error, generation=page_generation: self._remote_job_action_failed(error, generation),
        )

    def _import_remote_job(self, _button: Gtk.Button) -> None:
        import base64
        source_index = self.remote_import_source.get_selected()
        source = ("upload", "url", "repository", "scp")[source_index] if source_index < 4 else ""
        value = self.remote_import_path.get_text().strip()
        params: dict[str, Any] = {"source": source}
        if source == "upload":
            try:
                if not value:
                    raise ValueError("Indica la ruta local del archivo JSON.")
                payload = Path(value).expanduser().read_bytes()
                if not 1 <= len(payload) <= 64 * 1024:
                    raise ValueError("El archivo debe tener entre 1 byte y 64 KiB.")
                params["answer_base64"] = base64.b64encode(payload).decode("ascii")
            except (OSError, ValueError) as error:
                self.remote_job_result.set_text("No se pudo leer el archivo: " + str(error))
                return
        elif source == "url":
            if not value:
                self.remote_job_result.set_text("Indica una URL HTTP o HTTPS.")
                return
            params["url"] = value
        elif source in {"repository", "scp"}:
            selected = self.remote_import_repository.get_selected()
            rows = getattr(self, "_remote_import_rows", [])
            if selected == 0 or selected - 1 >= len(rows) or not value:
                self.remote_job_result.set_text("Selecciona repositorio y ruta relativa.")
                return
            repository = rows[selected - 1]
            if source == "scp" and repository.get("provider") != "sshfs":
                self.remote_job_result.set_text("SCP requiere un repositorio SSHFS con credenciales SSH protegidas.")
                return
            params["repository_id"] = repository.get("id")
            params["source_path"] = value
        else:
            self.remote_job_result.set_text("Selecciona un origen válido.")
            return
        page_generation = self._remote_jobs_page_generation
        self.remote_job_result.set_text("Descargando y validando definición; no se iniciará ningún servicio…")
        self.api.submit(
            "import_deployment_job", params,
            on_success=lambda result, generation=page_generation: self._remote_job_imported(result, generation),
            on_error=lambda error, generation=page_generation: self._remote_job_action_failed(error, generation),
        )

    def _remote_job_imported(
        self, result: dict[str, Any], page_generation: int | None = None
    ) -> None:
        self._remote_job_import_result = result
        if page_generation is not None and page_generation != self._remote_jobs_page_generation:
            return
        job = result.get("job")
        if not isinstance(job, dict):
            self.remote_job_result.set_text("El backend no devolvió una definición válida.")
            return
        self.remote_job_json.get_buffer().set_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n")
        self.remote_job_result.set_text(str(result.get("message") or "Definición importada; revísala y guárdala explícitamente."))

    @staticmethod
    def _gtk_deployment_arm_phrase(job: dict[str, Any]) -> str:
        job_id = str(job.get("job_id") or "")
        if job.get("operation") == "clone" and job.get("transport") == "multicast":
            return f"ARM PHYSICAL MULTICAST {job_id} FROM {job.get('source_device')} IGMP-VERIFIED"
        if job.get("transport") == "multicast":
            return f"ARM MULTICAST {job_id} IGMP-VERIFIED"
        if job.get("operation") == "clone":
            return f"ARM {job_id} AND READ {job.get('source_device')}"
        return f"ARM {job_id}"

    def _run_remote_job_action(self, _button: Gtk.Button) -> None:
        selected = self.remote_job_select.get_selected()
        jobs = getattr(self, "_remote_jobs", [])
        if selected == 0 or selected - 1 >= len(jobs):
            self.remote_job_result.set_text("Selecciona un trabajo persistido.")
            return
        job = jobs[selected - 1]
        job_id = str(job.get("job_id") or "")
        confirmation = self.remote_job_confirmation.get_text()
        actions = ("status", "start", "refresh", "arm", "cancel", "stop", "reconcile")
        action_index = self.remote_job_action.get_selected()
        if not job_id or action_index >= len(actions):
            self.remote_job_result.set_text("Trabajo o acción no válidos.")
            return
        action = actions[action_index]
        if action == "start":
            if job.get("interrupted") or job.get("job_state") != "created":
                self.remote_job_result.set_text("Solo se inicia el servicio de una definición nueva no interrumpida.")
                return
            self._submit_remote_job_action("start_deployment_service", {"job_id": job_id})
        elif action in {"status", "refresh"}:
            self._submit_remote_job_action("deployment_service_status", {"job_id": job_id})
        elif action == "arm":
            expected = self._gtk_deployment_arm_phrase(job)
            if job.get("job_state") != "created" or confirmation != expected:
                self.remote_job_result.set_text(f"El trabajo debe estar creado y requiere escribir exactamente: {expected}")
                return
            self._submit_remote_job_action("arm_deployment_job", {"job_id": job_id, "confirmation": confirmation})
        elif action == "cancel":
            expected = f"CANCEL {job_id}"
            if confirmation != expected:
                self.remote_job_result.set_text(f"Escribe exactamente: {expected}")
                return
            self._submit_remote_job_action("cancel_deployment_job", {"job_id": job_id, "confirmation": confirmation})
        elif action == "reconcile":
            expected = f"RECONCILE {job_id}"
            if not job.get("interrupted") or confirmation != expected:
                self.remote_job_result.set_text(f"El trabajo debe estar interrumpido y requiere escribir exactamente: {expected}")
                return
            self._submit_remote_job_action("reconcile_deployment_job", {"job_id": job_id, "confirmation": confirmation})
        elif action == "stop":
            page_generation = self._remote_jobs_page_generation
            self.remote_job_result.set_text("Comprobando que no haya workers ni clientes activos antes de detener…")
            self.api.submit(
                "deployment_service_status", {"job_id": job_id},
                on_success=lambda result, generation=page_generation: self._stop_remote_job_after_status(
                    job_id, result, generation
                ),
                on_error=lambda error, generation=page_generation: self._remote_job_action_failed(error, generation, job_id),
            )

    def _remote_job_context_is_current(
        self, page_generation: int | None, job_id: str | None
    ) -> bool:
        if page_generation is not None and page_generation != self._remote_jobs_page_generation:
            return False
        if job_id is None:
            return True
        selected = self.remote_job_select.get_selected()
        jobs = getattr(self, "_remote_jobs", [])
        return selected > 0 and selected - 1 < len(jobs) and str(jobs[selected - 1].get("job_id") or "") == job_id

    def _stop_remote_job_after_status(
        self, job_id: str, status: dict[str, Any], page_generation: int | None = None
    ) -> None:
        if not self._remote_job_context_is_current(page_generation, job_id):
            return
        clients = status.get("clients") or []
        running_clients = any(isinstance(item, dict) and item.get("state") == "running" for item in clients)
        if status.get("worker_active") or status.get("job_state") == "running" or running_clients:
            self.remote_job_result.set_text("No se detiene un worker ni una operación de cliente en curso.")
            return
        self._submit_remote_job_action("stop_deployment_service", {"job_id": job_id}, page_generation)

    def _submit_remote_job_action(
        self, action: str, params: dict[str, Any], page_generation: int | None = None
    ) -> None:
        generation = self._remote_jobs_page_generation if page_generation is None else page_generation
        job_id = str(params.get("job_id") or "") or None
        self.remote_job_result.set_text(f"Ejecutando {action}…")
        self.api.submit(
            action, params,
            on_success=lambda result: self._remote_job_action_done(result, generation, job_id, action),
            on_error=lambda error: self._remote_job_action_failed(error, generation, job_id),
        )

    def _remote_job_action_done(
        self, result: dict[str, Any], page_generation: int | None = None,
        job_id: str | None = None, action: str | None = None,
    ) -> None:
        results = getattr(self, "_remote_job_action_results", [])
        results.append({"action": action, "job_id": job_id, "result": result})
        self._remote_job_action_results = results
        if not self._remote_job_context_is_current(page_generation, job_id):
            return
        self.remote_job_confirmation.set_text("")
        self.remote_job_result.set_text(json.dumps(result, ensure_ascii=False, indent=2))
        generation = page_generation
        self.api.submit(
            "deployment_jobs",
            on_success=lambda response: self._populate_remote_job_controls(response)
            if self._remote_job_context_is_current(generation, job_id) else None,
            on_error=lambda error: self._remote_job_action_failed(error, generation, job_id),
        )

    def _remote_job_action_failed(
        self, error: Exception, page_generation: int | None = None,
        job_id: str | None = None,
    ) -> None:
        if not self._remote_job_context_is_current(page_generation, job_id):
            return
        self.remote_job_result.set_text("Acción remota no completada: " + str(error))

    def _show_deployments_page(self) -> None:
        def render(item: dict[str, Any]) -> tuple[str, ...]:
            clients = item.get("clients") or {}
            return (
                item.get("job_id") or "—", item.get("job_state") or "—",
                ", ".join(f"{mac}: {state}" for mac, state in clients.items()) or "—",
                item.get("event_count") or 0,
            )
        self._history_page("Historial de despliegues y eventos persistidos.", ("Despliegue", "Estado", "Clientes", "Eventos"), "journals", "journals", render)

    def _show_client_jobs_page(self) -> None:
        self._client_page_generation = getattr(self, "_client_page_generation", 0) + 1
        page_generation = self._client_page_generation
        self.page_description.set_text("Inspección TLS del servidor, selección segura de destino local y ejecución/seguimiento del cliente.")
        client_history_group = Adw.PreferencesGroup(title="Historial de clientes")
        self.page_body.append(client_history_group)
        self.history_summary = Gtk.Label(label="Consultando clientes…", xalign=0)
        client_summary_row = Adw.ActionRow(title="Estado")
        client_summary_row.add_suffix(self.history_summary)
        client_history_group.add(client_summary_row)
        refresh = Gtk.Button(label="Actualizar historial de clientes")
        refresh.connect("clicked", self._refresh_client_job_history)
        client_refresh_row = Adw.ActionRow(title="Actualizar")
        client_refresh_row.add_suffix(refresh)
        client_refresh_row.set_activatable_widget(refresh)
        client_history_group.add(client_refresh_row)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.history_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.history_grid)
        self.page_body.append(scroller)
        connection_group = Adw.PreferencesGroup(title="Conexión e inspección autenticada")
        self.page_body.append(connection_group)
        self.client_server_host = Gtk.Entry()
        self.client_server_host.set_placeholder_text("Host o dirección del servidor Feclora")
        host_row = Adw.ActionRow(title="Servidor Feclora")
        host_row.add_suffix(self.client_server_host)
        host_row.set_activatable_widget(self.client_server_host)
        connection_group.add(host_row)
        self.client_job_id = Gtk.Entry()
        self.client_job_id.set_placeholder_text("UUID del DeploymentJob")
        job_id_row = Adw.ActionRow(title="Identificador del trabajo")
        job_id_row.add_suffix(self.client_job_id)
        job_id_row.set_activatable_widget(self.client_job_id)
        connection_group.add(job_id_row)
        self.client_interface = Gtk.DropDown.new_from_strings(["Cargando interfaces IPv4 activas…"])
        interface_row = Adw.ActionRow(title="Interfaz IPv4 local")
        interface_row.add_suffix(self.client_interface)
        interface_row.set_activatable_widget(self.client_interface)
        connection_group.add(interface_row)
        inspect = Gtk.Button(label="Autenticar TLS e inspeccionar trabajo")
        inspect.connect("clicked", self._inspect_client_job)
        inspect_row = Adw.ActionRow(title="Inspección del servidor")
        inspect_row.add_suffix(inspect)
        inspect_row.set_activatable_widget(inspect)
        connection_group.add(inspect_row)
        self.client_job_details = Gtk.Label(label="Sin inspección autenticada.", xalign=0)
        self.client_job_details.set_wrap(True)
        self.client_job_details.set_selectable(True)
        details_row = Adw.ActionRow(title="Identidad y detalles autenticados")
        details_row.add_suffix(self.client_job_details)
        connection_group.add(details_row)

        target_group = Adw.PreferencesGroup(title="Destino local")
        self.page_body.append(target_group)
        self.client_target = Gtk.DropDown.new_from_strings(["Inspecciona primero el trabajo remoto…"])
        self.client_target.connect("notify::selected", self._update_client_confirmation)
        target_row = Adw.ActionRow(title="Dispositivo o volumen de destino")
        target_row.add_suffix(self.client_target)
        target_row.set_activatable_widget(self.client_target)
        target_group.add(target_row)

        transfer_group = Adw.PreferencesGroup(title="Transferencia y protección")
        self.page_body.append(transfer_group)
        self.client_compression = Gtk.DropDown.new_from_strings(["Gzip", "Zstandard", "LZ4", "Sin compresión"])
        compression_row = Adw.ActionRow(title="Compresión")
        compression_row.add_suffix(self.client_compression)
        compression_row.set_activatable_widget(self.client_compression)
        transfer_group.add(compression_row)
        self.client_encrypt = Gtk.DropDown.new_from_strings(["Sin cifrado", "Cifrar imagen con age"])
        encryption_row = Adw.ActionRow(title="Cifrado de imagen")
        encryption_row.add_suffix(self.client_encrypt)
        encryption_row.set_activatable_widget(self.client_encrypt)
        transfer_group.add(encryption_row)
        self.client_igmp = Gtk.CheckButton(label="Confirmo multicast en una red aislada con IGMP verificado")
        igmp_row = Adw.ActionRow(title="Multicast", subtitle="Solo en una red aislada con IGMP verificado")
        igmp_row.add_suffix(self.client_igmp)
        igmp_row.set_activatable_widget(self.client_igmp)
        transfer_group.add(igmp_row)

        execution_group = Adw.PreferencesGroup(title="Ejecución y seguimiento")
        self.page_body.append(execution_group)
        self.client_confirmation = Gtk.Entry()
        self.client_confirmation.set_placeholder_text("Escribe exactamente ERASE destino o READ destino TO identidad")
        confirmation_row = Adw.ActionRow(title="Confirmación exacta")
        confirmation_row.add_suffix(self.client_confirmation)
        confirmation_row.set_activatable_widget(self.client_confirmation)
        execution_group.add(confirmation_row)
        start = Gtk.Button(label="Iniciar operación del cliente")
        start.connect("clicked", self._start_client_job)
        start_row = Adw.ActionRow(title="Iniciar operación")
        start_row.add_suffix(start)
        start_row.set_activatable_widget(start)
        execution_group.add(start_row)
        status = Gtk.Button(label="Consultar estado del cliente")
        status.connect("clicked", self._refresh_client_job_status)
        status_row = Adw.ActionRow(title="Estado de ejecución")
        status_row.add_suffix(status)
        status_row.set_activatable_widget(status)
        execution_group.add(status_row)
        self.client_result = Gtk.Label(label="No se ha iniciado ningún trabajo.", xalign=0)
        self.client_result.set_wrap(True)
        self.client_result.set_selectable(True)
        result_row = Adw.ActionRow(title="Resultado")
        result_row.add_suffix(self.client_result)
        execution_group.add(result_row)
        self._client_remote_inspection = None
        self._client_network_interfaces = []
        self._client_inventory_devices = []
        self._client_logical_volumes = []
        self._client_inspection_generation = getattr(self, "_client_inspection_generation", 0) + 1
        self.client_server_host.connect("changed", self._client_inputs_changed)
        self.client_job_id.connect("changed", self._client_inputs_changed)
        self.client_interface.connect("notify::selected", self._client_inputs_changed)
        self._show_client_job_rows({"jobs": []})
        self._refresh_client_job_history()
        window_generation = self._page_generation
        self.api.submit(
            "network_interfaces",
            on_success=lambda response: self._populate_client_interfaces(response, page_generation, window_generation)
            if page_generation == self._client_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error: self._client_job_failed(error)
            if page_generation == self._client_page_generation and window_generation == self._page_generation else None,
        )
        self.api.submit(
            "inventory",
            on_success=lambda response: self._populate_client_inventory(response, page_generation, window_generation)
            if page_generation == self._client_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error: self._client_job_failed(error)
            if page_generation == self._client_page_generation and window_generation == self._page_generation else None,
        )

    def _refresh_client_job_history(self, _button: Gtk.Button | None = None) -> None:
        page_generation = self._client_page_generation
        self._client_history_generation = getattr(self, "_client_history_generation", 0) + 1
        request_generation = self._client_history_generation
        self.api.submit(
            "deployment_jobs",
            on_success=lambda response: self._show_client_job_rows(response)
            if page_generation == self._client_page_generation
            and request_generation == self._client_history_generation else None,
            on_error=lambda error: self._history_failed(error)
            if page_generation == self._client_page_generation
            and request_generation == self._client_history_generation else None,
        )

    def _populate_client_interfaces(
        self, response: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._client_page_generation or window_generation != self._page_generation
        ):
            return
        self._client_network_interfaces = [
            item for item in response.get("interfaces", [])
            if isinstance(item, dict) and item.get("binding") and item.get("interface") and item.get("address")
        ]
        labels = ["Selecciona interfaz IPv4 activa…"] + [
            f"{item['interface']} · {item['address']}" for item in self._client_network_interfaces
        ]
        self.client_interface.set_model(Gtk.StringList.new(labels))
        self.client_interface.set_selected(0)
        self._update_client_inventory_summary()

    def _invalidate_client_inspection(self) -> None:
        self._client_inspection_generation = getattr(self, "_client_inspection_generation", 0) + 1
        self._client_remote_inspection = None
        self._client_eligible_targets = []
        self.client_target.set_model(Gtk.StringList.new(["Inspecciona primero el trabajo remoto…"]))
        self.client_target.set_selected(0)
        self.client_job_details.set_text("Sin inspección autenticada.")
        self.client_confirmation.set_text("")
        self.client_confirmation.set_placeholder_text("Inspecciona primero el trabajo remoto")
 
    def _client_inputs_changed(self, *_args: Any) -> None:
        self._invalidate_client_inspection()

    def _populate_client_inventory(
        self, inventory: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._client_page_generation or window_generation != self._page_generation
        ):
            return
        self._invalidate_client_inspection()
        self._client_inventory_devices = self._flatten_devices(inventory.get("devices"))
        groups = inventory.get("volume_topology", {}).get("volume_groups", [])
        counts: dict[str, int] = {}
        for group in groups:
            if group.get("status") == "healthy":
                for volume in group.get("logical_volumes", []):
                    identity = volume.get("major_minor")
                    if identity:
                        counts[identity] = counts.get(identity, 0) + 1
        logical = []
        for group in groups:
            if group.get("status") != "healthy":
                continue
            for volume in group.get("logical_volumes", []):
                identity, size = volume.get("major_minor"), volume.get("size_bytes")
                if (volume.get("hidden") or volume.get("snapshot") or not identity or counts.get(identity) != 1
                        or not isinstance(size, int) or size <= 0
                        or volume.get("health") not in (None, "", "-", "ok", "healthy")):
                    continue
                matches = [device for device in self._client_inventory_devices if device.get("major_minor") == identity]
                if len(matches) == 1:
                    logical.append({**matches[0], "path": volume.get("path"), "size_bytes": size})
        self._client_logical_volumes = logical
        self._update_client_inventory_summary()

    def _update_client_inventory_summary(self) -> None:
        if hasattr(self, "history_summary"):
            self.history_summary.set_text(
                f"Dispositivos locales: {len(getattr(self, '_client_inventory_devices', []))} · "
                f"volúmenes LVM elegibles: {len(getattr(self, '_client_logical_volumes', []))} · "
                f"interfaces activas: {len(getattr(self, '_client_network_interfaces', []))}"
            )

    def _inspect_client_job(self, _button: Gtk.Button) -> None:
        host = self.client_server_host.get_text().strip()
        job_id = self.client_job_id.get_text().strip()
        selected = self.client_interface.get_selected()
        interfaces = getattr(self, "_client_network_interfaces", [])
        if not host or not job_id or selected == 0 or selected - 1 >= len(interfaces):
            self.client_result.set_text("Indica servidor, UUID e interfaz IPv4 activa.")
            return
        interface = interfaces[selected - 1]
        self._invalidate_client_inspection()
        inspection_generation = self._client_inspection_generation
        page_generation = self._client_page_generation
        self.client_target.set_model(Gtk.StringList.new(["Esperando inspección autenticada…"]))
        self.client_target.set_selected(0)
        self.client_result.set_text("Verificando TLS e identidad del servidor…")
        params = {
            "host": host, "job_id": job_id,
            "network_interface": interface["interface"], "source_address": interface["address"],
        }
        self.api.submit(
            "inspect_remote_job", params,
            on_success=lambda result: self._client_job_inspected(result)
            if page_generation == self._client_page_generation
            and inspection_generation == self._client_inspection_generation else None,
            on_error=lambda error: self._client_job_failed(error)
            if page_generation == self._client_page_generation
            and inspection_generation == self._client_inspection_generation else None,
        )

    def _client_job_inspected(self, result: dict[str, Any]) -> None:
        job = result.get("job")
        if not isinstance(job, dict):
            self._client_remote_inspection = None
            self.client_result.set_text("El servidor no devolvió una definición de trabajo válida.")
            return
        self._client_remote_inspection = result
        target_type = job.get("target_type")
        if target_type == "logical_volume":
            eligible = self._client_logical_volumes
        else:
            device_type = {"disk": "disk", "partition": "part"}.get(target_type)
            eligible = [item for item in self._client_inventory_devices if item.get("type") == device_type]
        self._client_eligible_targets = [item for item in eligible if item.get("path")]
        labels = ["Selecciona destino local…"] + [
            f"{item.get('path')} · {item.get('model') or item.get('type')} · {item.get('size_bytes', 0)} bytes"
            for item in self._client_eligible_targets
        ]
        self.client_target.set_model(Gtk.StringList.new(labels))
        self.client_target.set_selected(0)
        self.client_job_details.set_text(json.dumps({
            "server_identity": result.get("server_identity"), "job": job,
        }, ensure_ascii=False, indent=2))
        self.client_result.set_text("TLS e identidad del servidor verificados; no se inició ninguna operación.")
        self._update_client_confirmation(self.client_target, None)

    def _update_client_confirmation(self, _widget: Gtk.DropDown, _pspec: Any = None) -> None:
        inspection = getattr(self, "_client_remote_inspection", None)
        targets = getattr(self, "_client_eligible_targets", [])
        if not isinstance(inspection, dict) or not isinstance(inspection.get("job"), dict):
            return
        selected = self.client_target.get_selected()
        if selected == 0 or selected - 1 >= len(targets):
            self.client_confirmation.set_placeholder_text("Selecciona un destino local tras inspeccionar el servidor")
            return
        target = str(targets[selected - 1].get("path"))
        job = inspection["job"]
        phrase = (
            f"ERASE {target}" if job.get("operation") in {"restore", "clone"}
            else f"READ {target} TO {inspection.get('server_identity')}"
        )
        self.client_confirmation.set_placeholder_text(f"Confirmación exacta: {phrase}")

    def _start_client_job(self, _button: Gtk.Button) -> None:
        inspection = getattr(self, "_client_remote_inspection", None)
        if not isinstance(inspection, dict) or not isinstance(inspection.get("job"), dict):
            self.client_result.set_text("Autentica e inspecciona primero el trabajo del servidor.")
            return
        selected_target = self.client_target.get_selected()
        targets = getattr(self, "_client_eligible_targets", [])
        selected_interface = self.client_interface.get_selected()
        interfaces = getattr(self, "_client_network_interfaces", [])
        if selected_target == 0 or selected_target - 1 >= len(targets) or selected_interface == 0 or selected_interface - 1 >= len(interfaces):
            self.client_result.set_text("Selecciona un destino local y una interfaz IPv4 activa.")
            return
        job = inspection["job"]
        target = str(targets[selected_target - 1]["path"])
        interface = interfaces[selected_interface - 1]
        phrase = (
            f"ERASE {target}" if job.get("operation") in {"restore", "clone"}
            else f"READ {target} TO {inspection.get('server_identity')}"
        )
        confirmation = self.client_confirmation.get_text()
        if confirmation != phrase:
            self.client_result.set_text(f"Escribe exactamente: {phrase}")
            return
        compression_values = ("gzip", "zstd", "lz4", "none")
        compression_index = self.client_compression.get_selected()
        if compression_index >= len(compression_values):
            self.client_result.set_text("Selecciona un método de compresión válido.")
            return
        params = {
            "host": self.client_server_host.get_text().strip(), "job_id": job["job_id"],
            "device_path": target, "confirmation": confirmation,
            "compression": compression_values[compression_index],
            "image_encrypt": self.client_encrypt.get_selected() == 1,
            "network_interface": interface["interface"], "source_address": interface["address"],
            "igmp_confirmed": self.client_igmp.get_active() if job.get("transport") == "multicast" else False,
        }
        if job.get("transport") == "multicast" and not params["igmp_confirmed"]:
            self.client_result.set_text("El trabajo multicast requiere confirmación explícita de IGMP/red aislada.")
            return
        page_generation = self._client_page_generation
        inspection_generation = self._client_inspection_generation
        job_id = str(job.get("job_id") or "")
        self.client_result.set_text("Iniciando cliente; el backend volverá a comprobar identidad, destino y confirmación…")
        self.api.submit(
            "start_client_job", params,
            on_success=lambda result: self._client_job_started(
                result, page_generation, inspection_generation, job_id
            ),
            on_error=lambda error: self._client_job_failed(
                error, page_generation, inspection_generation, job_id
            ),
        )

    def _client_job_started(
        self, result: dict[str, Any], page_generation: int | None = None,
        inspection_generation: int | None = None, job_id: str | None = None,
    ) -> None:
        # Preserve a completed start response even if navigation or a new inspection
        # made its original controls stale while the privileged action was running.
        results = getattr(self, "_client_remote_job_results", {})
        results[job_id or str(result.get("job_id") or "latest")] = result
        self._client_remote_job_results = results
        if page_generation is not None and (
            page_generation != self._client_page_generation
            or inspection_generation != self._client_inspection_generation
        ):
            return
        self._client_remote_job_status = result
        self.client_confirmation.set_text("")
        self.client_result.set_text(json.dumps(result, ensure_ascii=False, indent=2))

    def _refresh_client_job_status(self, _button: Gtk.Button) -> None:
        inspection = getattr(self, "_client_remote_inspection", None)
        job = inspection.get("job") if isinstance(inspection, dict) else None
        if not isinstance(job, dict) or not job.get("job_id"):
            self.client_result.set_text("Inspecciona primero el trabajo remoto.")
            return
        page_generation = self._client_page_generation
        inspection_generation = self._client_inspection_generation
        self._client_status_generation = getattr(self, "_client_status_generation", 0) + 1
        status_generation = self._client_status_generation
        job_id = str(job["job_id"])
        self.client_result.set_text("Consultando estado del cliente…")
        self.api.submit(
            "client_job_status", {"job_id": job_id},
            on_success=lambda result: self._client_job_status_loaded(
                result, page_generation, inspection_generation, status_generation, job_id
            ),
            on_error=lambda error: self._client_job_failed(
                error, page_generation, inspection_generation, job_id
            ),
        )

    def _client_job_status_loaded(
        self, result: dict[str, Any], page_generation: int | None = None,
        inspection_generation: int | None = None, status_generation: int | None = None,
        job_id: str | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._client_page_generation
            or inspection_generation != self._client_inspection_generation
            or status_generation != self._client_status_generation
        ):
            return
        inspection = getattr(self, "_client_remote_inspection", None)
        current_job = inspection.get("job") if isinstance(inspection, dict) else None
        if job_id is not None and (
            not isinstance(current_job, dict) or str(current_job.get("job_id") or "") != job_id
        ):
            return
        self._client_remote_job_status = result
        self.client_result.set_text(json.dumps(result, ensure_ascii=False, indent=2))

    def _client_job_failed(
        self, error: Exception, page_generation: int | None = None,
        inspection_generation: int | None = None, job_id: str | None = None,
    ) -> None:
        if page_generation is not None and (
            page_generation != self._client_page_generation
            or inspection_generation != self._client_inspection_generation
        ):
            return
        self.client_result.set_text("Operación de cliente no completada: " + str(error))

    def _show_client_job_rows(self, response: dict[str, Any]) -> None:
        grid = self.history_grid
        while child := grid.get_first_child():
            grid.remove(child)
        for column, heading in enumerate(("Trabajo", "Cliente", "Estado")):
            label = Gtk.Label(label=heading, xalign=0)
            label.add_css_class("heading")
            grid.attach(label, column, 0, 1, 1)
        count = 0
        for job in response.get("jobs") or []:
            clients = job.get("clients") or {}
            for mac, details in clients.items():
                for column, value in enumerate((job.get("job_id") or "—", mac, details.get("state") or "—")):
                    label = Gtk.Label(label=str(value), xalign=0)
                    label.set_selectable(True)
                    grid.attach(label, column, count + 1, 1, 1)
                count += 1
        self.history_summary.set_text(f"Clientes registrados: {count}")

    def _show_operation_log_page(self) -> None:
        self._operation_log_page_generation = self._page_generation
        self.page_description.set_text("Historial persistente de operaciones locales, incluidos errores y estados terminales.")

        status_group = Adw.PreferencesGroup(
            title="Estado del registro",
            description="Consulta el historial persistido de operaciones locales",
        )
        self.page_body.append(status_group)
        self.operation_log_summary = Gtk.Label(label="Consultando operaciones…", xalign=0)
        self.operation_log_summary.set_selectable(True)
        summary_row = Adw.ActionRow(title="Resumen de operaciones")
        summary_row.add_suffix(self.operation_log_summary)
        status_group.add(summary_row)
        refresh = Gtk.Button(label="Actualizar registro")
        refresh.connect("clicked", self._refresh_operation_log)
        refresh_row = Adw.ActionRow(title="Actualizar historial")
        refresh_row.add_suffix(refresh)
        refresh_row.set_activatable_widget(refresh)
        status_group.add(refresh_row)

        cancel_group = Adw.PreferencesGroup(
            title="Cancelación controlada",
            description="La solicitud solo se acepta con la frase exacta CANCEL <operation_id>",
        )
        self.page_body.append(cancel_group)
        self.operation_select = Gtk.DropDown.new_from_strings(["Selecciona operación…"])
        select_row = Adw.ActionRow(title="Operación local")
        select_row.add_suffix(self.operation_select)
        select_row.set_activatable_widget(self.operation_select)
        cancel_group.add(select_row)
        self.operation_confirmation = Gtk.Entry()
        self.operation_confirmation.set_placeholder_text("CANCEL <operation_id>")
        confirmation_row = Adw.ActionRow(title="Confirmación exacta")
        confirmation_row.add_suffix(self.operation_confirmation)
        cancel_group.add(confirmation_row)
        cancel = Gtk.Button(label="Solicitar cancelación")
        cancel.connect("clicked", self._cancel_selected_logged_operation)
        cancel_row = Adw.ActionRow(title="Cancelar operación seleccionada")
        cancel_row.add_suffix(cancel)
        cancel_row.set_activatable_widget(cancel)
        cancel_group.add(cancel_row)

        history_group = Adw.PreferencesGroup(
            title="Operaciones registradas",
            description="Los estados vacíos y los resultados se muestran por separado",
        )
        self.page_body.append(history_group)
        self.operation_log_inspection_group = Adw.PreferencesGroup(
            title="Errores de inspección",
            description="Registros que el backend no pudo inspeccionar de forma completa.",
        )
        self.page_body.append(self.operation_log_inspection_group)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.operation_log_stack = Gtk.Stack()
        self.operation_log_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        self.operation_log_stack.add_named(self.operation_log_grid, "records")
        self.operation_log_empty = Adw.StatusPage(
            title="Sin operaciones registradas",
            description="Las operaciones locales aparecerán aquí cuando se ejecuten.",
            icon_name="view-list-symbolic",
        )
        self.operation_log_stack.add_named(self.operation_log_empty, "empty")
        scroller.set_child(self.operation_log_stack)
        history_group.add(scroller)
        self._refresh_operation_log(None)

    def _refresh_operation_log(self, _button: Gtk.Button | None) -> None:
        self._operation_log_refresh_generation = getattr(self, "_operation_log_refresh_generation", 0) + 1
        generation = self._operation_log_refresh_generation
        page_generation = self._operation_log_page_generation
        self.operation_log_summary.set_text("Leyendo el registro duradero…")
        self.api.submit(
            "local_operations",
            on_success=lambda response: self._show_operation_log(response)
            if page_generation == self._page_generation and generation == self._operation_log_refresh_generation else None,
            on_error=lambda error: self._operation_log_failed(error, page_generation)
            if page_generation == self._page_generation and generation == self._operation_log_refresh_generation else None,
        )

    def _show_operation_log(self, response: dict[str, Any]) -> None:
        grid = self.operation_log_grid
        while child := grid.get_first_child():
            grid.remove(child)
        headers = ("ID", "Acción", "Estado", "Último evento", "Progreso", "Detalles")
        for column, heading in enumerate(headers):
            label = Gtk.Label(label=heading, xalign=0)
            label.add_css_class("heading")
            grid.attach(label, column, 0, 1, 1)
        operations = response.get("operations") or []
        self.operation_log_records = [item for item in operations if isinstance(item, dict) and item.get("operation_id")]
        options = [str(item["operation_id"]) + " · " + str(item.get("action") or "—") + " · " + str(item.get("state") or "unknown") for item in self.operation_log_records]
        self.operation_select.set_model(Gtk.StringList.new(options or ["No hay operaciones registradas"]))
        self.operation_select.set_selected(0)
        for row, item in enumerate(operations, start=1):
            events = item.get("events") or []
            latest = events[-1] if events else {}
            details = latest.get("details") or {}
            progress = next((event.get("details") or {} for event in reversed(events) if event.get("state") == "progress"), {})
            total, done = progress.get("bytes_total"), progress.get("bytes_done", 0)
            progress_text = f"{done} / {total} bytes" if isinstance(total, int) and isinstance(done, int) else "—"
            detail_text = details.get("error") or details.get("reason") or ("Destino posiblemente parcial" if details.get("destination_may_be_partial") else "—")
            values = (item.get("operation_id") or "—", item.get("action") or "—", item.get("state") or "unknown", latest.get("timestamp") or "—", progress_text, detail_text)
            for column, value in enumerate(values):
                label = Gtk.Label(label=str(value), xalign=0)
                label.set_selectable(True)
                label.set_wrap(True)
                grid.attach(label, column, row, 1, 1)
        errors = response.get("inspection_errors") or []
        self.operation_log_empty.set_title("Sin operaciones registradas")
        self.operation_log_empty.set_description("Las operaciones locales aparecerán aquí cuando se ejecuten.")
        self.operation_log_stack.set_visible_child_name("records" if operations else "empty")
        if errors:
            self.operation_log_empty.set_title("Hay registros que requieren inspección manual")
            self.operation_log_empty.set_description(
                "No repitas operaciones afectadas hasta revisar los errores de inspección."
            )
            self.operation_log_stack.set_visible_child_name("records" if operations else "empty")
        self.operation_log_summary.set_text(
            f"Operaciones registradas: {len(operations)} · errores de inspección: {len(errors)}"
            + (" · ATENCIÓN: no repitas operaciones afectadas hasta inspección manual." if errors else "")
        )
        self.operation_log_inspection_errors = [
            item for item in errors if isinstance(item, dict)
        ]
        error_group = self.operation_log_inspection_group
        while child := error_group.get_first_child():
            error_group.remove(child)
        error_group.set_description(
            "No repitas operaciones afectadas hasta revisar estos errores."
            if self.operation_log_inspection_errors
            else "No hay errores de inspección comunicados por el backend."
        )
        for item in self.operation_log_inspection_errors:
            path = item.get("path") or item.get("operation_id") or "Registro desconocido"
            reason = item.get("error") or item.get("reason") or "Error de inspección sin detalle"
            error_group.add(Adw.ActionRow(title=str(path), subtitle=str(reason)))

    def _cancel_selected_logged_operation(self, _button: Gtk.Button) -> None:
        index = self.operation_select.get_selected()
        if index >= len(getattr(self, "operation_log_records", [])):
            self.operation_log_summary.set_text("Selecciona una operación registrada.")
            return
        operation_id = self.operation_log_records[index]["operation_id"]
        expected = "CANCEL " + operation_id
        if self.operation_confirmation.get_text() != expected:
            self.operation_log_summary.set_text("Escribe exactamente: " + expected)
            return
        page_generation = self._operation_log_page_generation
        self.api.submit(
            "cancel_local_operation", {"operation_id": operation_id},
            on_success=lambda result: self._operation_cancelled(result, operation_id, page_generation),
            on_error=lambda error: self._operation_log_failed(error, page_generation, operation_id),
        )

    def _operation_cancelled(
        self, result: dict[str, Any], operation_id: str | None = None,
        page_generation: int | None = None,
    ) -> None:
        if page_generation != self._page_generation or page_generation != getattr(self, "_operation_log_page_generation", None):
            return
        selected_index = self.operation_select.get_selected()
        selected_id = self.operation_log_records[selected_index]["operation_id"] if selected_index < len(getattr(self, "operation_log_records", [])) else None
        if operation_id and selected_id != operation_id:
            return
        self.operation_confirmation.set_text("")
        self.operation_log_summary.set_text("Resultado de cancelación: " + str(result))
        self._refresh_operation_log(None)

    def _operation_log_failed(
        self, error: Exception, page_generation: int | None = None,
        operation_id: str | None = None,
    ) -> None:
        self._operation_log_errors = getattr(self, "_operation_log_errors", {})
        if operation_id:
            self._operation_log_errors[operation_id] = str(error)
        if page_generation is not None and (
            page_generation != self._page_generation
            or page_generation != getattr(self, "_operation_log_page_generation", None)
        ):
            return
        if operation_id is not None:
            selected_index = self.operation_select.get_selected()
            selected_id = self.operation_log_records[selected_index]["operation_id"] if selected_index < len(getattr(self, "operation_log_records", [])) else None
            if selected_id != operation_id:
                return
        self.operation_log_stack.set_visible_child_name("empty")
        self.operation_log_empty.set_title("No se pudo consultar el registro")
        self.operation_log_empty.set_description(str(error))
        self.operation_log_summary.set_text("No se pudo leer el registro de operaciones: " + str(error))

    def _show_recovery_jobs_page(self) -> None:
        self._recovery_jobs_page_generation = self._page_generation
        self.page_description.set_text("Trabajos ddrescue persistentes. Los mapfiles permiten reanudar recuperaciones interrumpidas.")

        status_group = Adw.PreferencesGroup(
            title="Estado de recuperación",
            description="Trabajos persistentes de ddrescue y sus mapfiles",
        )
        self.page_body.append(status_group)
        self.recovery_jobs_summary = Gtk.Label(label="Consultando trabajos…", xalign=0)
        self.recovery_jobs_summary.set_selectable(True)
        summary_row = Adw.ActionRow(title="Resumen de trabajos")
        summary_row.add_suffix(self.recovery_jobs_summary)
        status_group.add(summary_row)
        refresh = Gtk.Button(label="Actualizar recuperaciones")
        refresh.connect("clicked", self._refresh_recovery_jobs)
        refresh_row = Adw.ActionRow(title="Actualizar historial")
        refresh_row.add_suffix(refresh)
        refresh_row.set_activatable_widget(refresh)
        status_group.add(refresh_row)

        history_group = Adw.PreferencesGroup(
            title="Trabajos ddrescue",
            description="Progreso, bytes pendientes y resultados parciales de recuperación",
        )
        self.page_body.append(history_group)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.recovery_jobs_stack = Gtk.Stack()
        self.recovery_jobs_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        self.recovery_jobs_stack.add_named(self.recovery_jobs_grid, "jobs")
        self.recovery_jobs_empty = Adw.StatusPage(
            title="Sin trabajos de recuperación",
            description="Los trabajos ddrescue persistentes aparecerán aquí.",
            icon_name="drive-harddisk-symbolic",
        )
        self.recovery_jobs_stack.add_named(self.recovery_jobs_empty, "empty")
        scroller.set_child(self.recovery_jobs_stack)
        history_group.add(scroller)
        self._refresh_recovery_jobs(None)

    def _refresh_recovery_jobs(self, _button: Gtk.Button | None) -> None:
        self._recovery_jobs_refresh_generation = getattr(self, "_recovery_jobs_refresh_generation", 0) + 1
        generation = self._recovery_jobs_refresh_generation
        page_generation = self._recovery_jobs_page_generation
        self.recovery_jobs_summary.set_text("Leyendo trabajos ddrescue…")
        self.api.submit(
            "recovery_jobs",
            on_success=lambda response: self._show_recovery_jobs(response)
            if page_generation == self._page_generation and generation == self._recovery_jobs_refresh_generation else None,
            on_error=lambda error: self._recovery_jobs_failed(error)
            if page_generation == self._page_generation and generation == self._recovery_jobs_refresh_generation else None,
        )

    def _show_recovery_jobs(self, response: dict[str, Any]) -> None:
        grid = self.recovery_jobs_grid
        while child := grid.get_first_child():
            grid.remove(child)
        headers = ("Trabajo", "Estado", "Origen", "Recuperado", "Pendiente", "Progreso")
        for column, heading in enumerate(headers):
            label = Gtk.Label(label=heading, xalign=0)
            label.add_css_class("heading")
            grid.attach(label, column, 0, 1, 1)
        jobs = response.get("jobs") or []
        for row, item in enumerate(jobs, start=1):
            size, rescued = item.get("source_size_bytes"), item.get("rescued_bytes")
            progress = item.get("progress_percent")
            recovered = f"{rescued:,} / {size:,} bytes" if isinstance(rescued, int) and isinstance(size, int) else "—"
            unresolved = item.get("unresolved_bytes")
            pending = f"{unresolved:,} bytes" if isinstance(unresolved, int) else "—"
            percent = f"{progress:.2f}%" if isinstance(progress, (int, float)) else "—"
            values = (item.get("job_id") or "—", item.get("state") or "—", item.get("source_path") or "—", recovered, pending, percent)
            for column, value in enumerate(values):
                label = Gtk.Label(label=str(value), xalign=0)
                label.set_selectable(True)
                grid.attach(label, column, row, 1, 1)
        self.recovery_jobs_empty.set_title("Sin trabajos de recuperación")
        self.recovery_jobs_empty.set_description("Los trabajos ddrescue persistentes aparecerán aquí.")
        self.recovery_jobs_stack.set_visible_child_name("jobs" if jobs else "empty")
        self.recovery_jobs_summary.set_text(f"Trabajos de recuperación: {len(jobs)} · los trabajos interrumpidos conservan su mapfile para reanudación")

    def _recovery_jobs_failed(self, error: Exception) -> None:
        self.recovery_jobs_stack.set_visible_child_name("empty")
        self.recovery_jobs_empty.set_title("No se pudieron consultar los trabajos")
        self.recovery_jobs_empty.set_description(str(error))
        self.recovery_jobs_summary.set_text("No se pudieron consultar los trabajos ddrescue: " + str(error))

    def _show_network_page(self) -> None:
        self._network_page_generation = getattr(self, "_network_page_generation", 0) + 1
        page_generation = self._network_page_generation
        window_generation = self._page_generation
        self.page_description.set_text("Configuración IPv4 de perfiles activos de NetworkManager, con aplicación protegida por checkpoint y rollback.")
        network_group = Adw.PreferencesGroup(
            title="Conexión IPv4",
            description="Selecciona un perfil activo y configura DHCP o una dirección estática.",
        )
        self.page_body.append(network_group)

        def add_network_combo(title: str, labels: list[str]) -> Adw.ComboRow:
            row = Adw.ComboRow(title=title)
            row.set_model(Gtk.StringList.new(labels))
            network_group.add(row)
            return row

        def add_network_entry(title: str) -> Adw.EntryRow:
            row = Adw.EntryRow(title=title)
            network_group.add(row)
            return row

        self.network_profile = add_network_combo("Perfil activo de NetworkManager", ["Cargando perfiles…"])
        self.network_profile.connect("notify::selected", self._network_profile_changed)
        self.network_interface = add_network_combo("Dirección IPv4 actualmente asociada", ["Selecciona interfaz y dirección…"])
        self.network_method = add_network_combo("Método IPv4", ["Automática (DHCP)", "Manual (IPv4 estática)"])
        self.network_method.connect("notify::selected", self._network_method_changed)
        self.network_address = add_network_entry("Dirección IPv4")
        self.network_address_row = self.network_address
        self.network_prefix = add_network_entry("Prefijo CIDR (1–32)")
        self.network_prefix_row = self.network_prefix
        self.network_gateway = add_network_entry("Gateway IPv4 (opcional)")
        self.network_gateway_row = self.network_gateway
        self.network_dns = add_network_entry("DNS IPv4 separados por comas")
        self.network_dns_row = self.network_dns
        apply = Gtk.Button(label="Aplicar configuración (rollback automático si falla)")
        apply.set_halign(Gtk.Align.START)
        apply.connect("clicked", self._apply_network_profile)
        self.page_body.append(apply)
        self.network_result = Gtk.Label(label="", xalign=0)
        self.network_result.set_wrap(True)
        self.page_body.append(self.network_result)
        self._network_method_changed(self.network_method, None)
        self.network_active_profiles = []
        self.network_interfaces = []
        self.network_interface_records = []
        self.api.submit(
            "network_connection_profiles",
            on_success=lambda result: self._populate_network_profiles(result)
            if page_generation == self._network_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error, page=page_generation, window=window_generation: self._network_failed(error, page, window)
            if page == self._network_page_generation and window == self._page_generation else None,
        )
        self.api.submit(
            "network_interfaces",
            on_success=lambda result: self._populate_network_interfaces(result)
            if page_generation == self._network_page_generation else None,
            on_error=lambda error, page=page_generation, window=window_generation: self._network_failed(error, page, window)
            if page == self._network_page_generation and window == self._page_generation else None,
        )

    def _populate_network_profiles(self, result: dict[str, Any]) -> None:
        self.network_profiles = [item for item in result.get("profiles", []) if isinstance(item, dict)]
        active = [item for item in self.network_profiles if item.get("uuid") and item.get("active") and item.get("device")]
        labels = ["Selecciona perfil activo…"] + [
            f"{item.get('name') or item.get('id')} · {item.get('device')}" for item in active
        ]
        self.network_active_profiles = active
        self.network_profile.set_model(Gtk.StringList.new(labels))
        self.network_profile.set_selected(0)
        self._update_network_interface_options()

    def _populate_network_interfaces(self, result: dict[str, Any]) -> None:
        self.network_interfaces = [item for item in result.get("interfaces", []) if isinstance(item, dict)]
        self._update_network_interface_options()

    def _network_profile_changed(self, _row: Adw.ComboRow, _pspec: Any) -> None:
        self._update_network_interface_options()

    def _update_network_interface_options(self) -> None:
        index = self.network_profile.get_selected()
        profile = self.network_active_profiles[index - 1] if 0 < index <= len(getattr(self, "network_active_profiles", [])) else None
        interface_name = profile.get("device") if profile else None
        candidates = [item for item in getattr(self, "network_interfaces", []) if item.get("binding") and item.get("interface") == interface_name]
        labels = ["Selecciona interfaz y dirección…"] + [
            f"{item.get('interface')} · {item.get('address')}/{item.get('prefix_length')}" for item in candidates
        ]
        self.network_interface_records = candidates
        self.network_interface.set_model(Gtk.StringList.new(labels))
        self.network_interface.set_selected(0)

    def _network_method_changed(self, _row: Adw.ComboRow, _pspec: Any) -> None:
        manual = self.network_method.get_selected() == 1
        for row in (self.network_address_row, self.network_prefix_row, self.network_gateway_row, self.network_dns_row):
            row.set_visible(manual)

    def _apply_network_profile(self, _button: Gtk.Button) -> None:
        import ipaddress
        profile_index = self.network_profile.get_selected()
        interface_index = self.network_interface.get_selected()
        if (profile_index == 0 or profile_index > len(getattr(self, "network_active_profiles", []))
                or interface_index == 0 or interface_index > len(getattr(self, "network_interface_records", []))):
            self.network_result.set_text("Selecciona un perfil activo y una dirección IPv4 de su interfaz.")
            return
        profile = self.network_active_profiles[profile_index - 1]
        interface = self.network_interface_records[interface_index - 1]
        if not profile.get("active") or not profile.get("device") or interface.get("interface") != profile.get("device"):
            self.network_result.set_text("El perfil debe estar activo y coincidir con la interfaz seleccionada.")
            return
        method = "manual" if self.network_method.get_selected() == 1 else "auto"
        params: dict[str, Any] = {
            "uuid": profile["uuid"], "interface": interface["interface"], "method": method,
            "address": None, "prefix_length": None, "gateway": None, "dns": [],
            "rollback_timeout": 120,
        }
        if method == "manual":
            try:
                address = ipaddress.IPv4Address(self.network_address.get_text().strip())
                prefix = int(self.network_prefix.get_text().strip())
                if not 1 <= prefix <= 32:
                    raise ValueError("el prefijo debe estar entre 1 y 32")
                gateway_text = self.network_gateway.get_text().strip()
                gateway = ipaddress.IPv4Address(gateway_text) if gateway_text else None
                dns = [str(ipaddress.IPv4Address(value.strip())) for value in self.network_dns.get_text().split(",") if value.strip()]
            except ValueError as exc:
                self.network_result.set_text("Dirección, prefijo, gateway o DNS no válido: " + str(exc))
                return
            params.update(address=str(address), prefix_length=prefix, gateway=str(gateway) if gateway else None, dns=dns)
        page_generation = self._network_page_generation
        window_generation = self._page_generation
        self._network_apply_generation = getattr(self, "_network_apply_generation", 0) + 1
        apply_generation = self._network_apply_generation
        self.network_result.set_text("Aplicando perfil con checkpoint de 120 segundos…")
        self.api.submit(
            "apply_network_profile", params,
            on_success=lambda result, page=page_generation, window=window_generation, request=apply_generation: self._network_applied(result, page, window, request)
            if page == self._network_page_generation and window == self._page_generation and request == self._network_apply_generation else None,
            on_error=lambda error, page=page_generation, window=window_generation, request=apply_generation: self._network_failed(error, page, window)
            if page == self._network_page_generation and window == self._page_generation and request == self._network_apply_generation else None,
        )

    def _network_applied(self, result: dict[str, Any], page_generation: int | None = None, window_generation: int | None = None, apply_generation: int | None = None) -> None:
        if page_generation is not None and (page_generation != self._network_page_generation or window_generation != self._page_generation or apply_generation != getattr(self, "_network_apply_generation", None)):
            return
        self.network_result.set_text(str(result.get("message") or "Perfil aplicado y verificado; checkpoint confirmado."))
        self.network_active_profiles = []
        self.network_interfaces = []
        self.network_interface_records = []
        self.network_profile.set_model(Gtk.StringList.new(["Cargando perfiles…"]))
        self.network_profile.set_selected(0)
        self.network_interface.set_model(Gtk.StringList.new(["Selecciona interfaz y dirección…"]))
        self.network_interface.set_selected(0)
        current_generation = self._network_page_generation
        current_window_generation = self._page_generation
        self.api.submit(
            "network_connection_profiles",
            on_success=lambda response: self._populate_network_profiles(response)
            if current_generation == self._network_page_generation and current_window_generation == self._page_generation else None,
            on_error=lambda error, page=current_generation, window=current_window_generation: self._network_failed(error, page, window)
            if page == self._network_page_generation and window == self._page_generation else None,
        )
        self.api.submit(
            "network_interfaces",
            on_success=lambda response: self._populate_network_interfaces(response)
            if current_generation == self._network_page_generation and current_window_generation == self._page_generation else None,
            on_error=lambda error, page=current_generation, window=current_window_generation: self._network_failed(error, page, window)
            if page == self._network_page_generation and window == self._page_generation else None,
        )

    def _network_failed(self, error: Exception, page_generation: int | None = None, window_generation: int | None = None) -> None:
        if page_generation is not None and (page_generation != self._network_page_generation or window_generation != self._page_generation):
            return
        self._network_action_errors = getattr(self, "_network_action_errors", [])
        self._network_action_errors.append(str(error))
        if hasattr(self, "network_result"):
            self.network_result.set_text("No se pudo completar la operación de red: " + str(error))

    def _show_restore_profiles_page(self) -> None:
        self._profile_page_generation = self._page_generation
        page_generation = self._profile_page_generation
        self.page_description.set_text("Perfiles de restauración de un solo uso, vinculados a la identidad física del disco y con caducidad.")

        def add_profile_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget, subtitle: str = "") -> Adw.ActionRow:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.add_suffix(widget)
            row.set_activatable_widget(widget)
            group.add(row)
            return row

        source_group = Adw.PreferencesGroup(
            title="Origen y destino",
            description="Selecciona una imagen RAW persistida y un disco identificado físicamente",
        )
        self.page_body.append(source_group)
        self.profile_repository = Gtk.DropDown.new_from_strings(["Cargando repositorios…"])
        add_profile_row(source_group, "Repositorio persistente", self.profile_repository, "Debe estar montado, verificado y ser escribible")
        self.profile_image = Gtk.DropDown.new_from_strings(["Selecciona imagen RAW de disco…"])
        add_profile_row(source_group, "Imagen RAW de disco", self.profile_image)
        self.profile_target = Gtk.DropDown.new_from_strings(["Cargando discos…"])
        add_profile_row(source_group, "Disco destino", self.profile_target, "Requiere WWN o número de serie")

        profile_group = Adw.PreferencesGroup(
            title="Definición del perfil",
            description="Crear un perfil no inicia la restauración",
        )
        self.page_body.append(profile_group)
        self.profile_name = Gtk.Entry()
        self.profile_name.set_placeholder_text("Nombre descriptivo del perfil")
        add_profile_row(profile_group, "Nombre del perfil", self.profile_name)
        self.profile_expiry = Gtk.Entry()
        self.profile_expiry.set_placeholder_text("2027-01-31T23:59:59+01:00")
        add_profile_row(profile_group, "Caducidad", self.profile_expiry, "Fecha ISO-8601 con zona horaria")
        create = Gtk.Button(label="Crear perfil")
        create.connect("clicked", self._create_restore_profile)
        add_profile_row(profile_group, "Guardar perfil de un solo uso", create)

        execution_group = Adw.PreferencesGroup(
            title="Ejecución controlada",
            description="La ejecución exige confirmar exactamente el disco físico detectado",
        )
        self.page_body.append(execution_group)
        self.profile_select = Gtk.DropDown.new_from_strings(["Cargando perfiles…"])
        add_profile_row(execution_group, "Perfil guardado", self.profile_select)
        self.profile_confirmation = Gtk.Entry()
        self.profile_confirmation.set_placeholder_text("ERASE /dev/…")
        add_profile_row(execution_group, "Confirmación exacta", self.profile_confirmation, "Debe coincidir con el destino seleccionado")
        execute = Gtk.Button(label="Ejecutar perfil de restauración")
        execute.connect("clicked", self._execute_selected_restore_profile)
        add_profile_row(execution_group, "Iniciar restauración", execute)
        self.profile_cancel = Gtk.Button(label="Solicitar cancelación de restauración")
        self.profile_cancel.set_sensitive(False)
        self.profile_cancel.connect("clicked", self._cancel_restore_profile_operation)
        add_profile_row(execution_group, "Cancelar operación activa", self.profile_cancel)

        self.profile_result = Gtk.Label(label="", xalign=0)
        self.profile_result.set_wrap(True)
        self.profile_result.set_selectable(True)
        result_row = Adw.ActionRow(title="Resultado")
        result_row.add_suffix(self.profile_result)
        execution_group.add(result_row)

        self.api.submit("inventory", on_success=lambda result: self._populate_profile_inventory(result) if page_generation == self._page_generation else None, on_error=lambda error: self._profile_failed(error, page_generation) if page_generation == self._page_generation else None)
        self.api.submit("remote_repositories", on_success=lambda result: self._populate_profile_repositories(result) if page_generation == self._page_generation else None, on_error=lambda error: self._profile_failed(error, page_generation) if page_generation == self._page_generation else None)
        pending_operation_id = getattr(self, "_latest_profile_operation_id", None)
        if pending_operation_id:
            self.profile_operation_id = pending_operation_id
            self.profile_cancel.set_sensitive(True)
            self.profile_result.set_text("Recuperando seguimiento de restauración " + pending_operation_id + "…")
            self._poll_restore_profile_operation(pending_operation_id, page_generation)

    def _populate_profile_inventory(self, inventory: dict[str, Any]) -> None:
        self.profile_inventory_devices = self._flatten_devices(inventory.get("devices"))
        disks = [item for item in self.profile_inventory_devices if item.get("type") == "disk" and (item.get("wwn") or item.get("serial"))]
        self.profile_target_devices = disks
        labels = [f"{item.get('path')} · {item.get('model') or 'Disco'} · {item.get('wwn') or item.get('serial')}" for item in disks]
        self.profile_target.set_model(Gtk.StringList.new(labels or ["No hay discos con identidad estable"]))
        self.profile_target.set_selected(0)

    def _populate_profile_repositories(self, result: dict[str, Any]) -> None:
        self.profile_repositories = [item for item in result.get("repositories", []) if isinstance(item, dict) and item.get("id") and item.get("mounted") and item.get("verified") and not item.get("read_only")]
        labels = [str(item["id"]) + " · " + str(item.get("provider") or "filesystem") for item in self.profile_repositories]
        self.profile_repository.set_model(Gtk.StringList.new(labels or ["No hay repositorios válidos"]))
        self.profile_repository.set_selected(0)
        self.profile_repository.connect("notify::selected", self._profile_repository_changed)
        self._load_restore_profiles_for_repository()

    def _selected_profile_repository(self) -> dict[str, Any] | None:
        index = self.profile_repository.get_selected()
        return self.profile_repositories[index] if index < len(getattr(self, "profile_repositories", [])) else None

    def _profile_repository_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._load_restore_profiles_for_repository()

    def _load_restore_profiles_for_repository(self) -> None:
        self._profile_repository_generation = getattr(self, "_profile_repository_generation", 0) + 1
        generation = self._profile_repository_generation
        page_generation = self._profile_page_generation
        repository = self._selected_profile_repository()
        self.profile_images = []
        self.profile_records = []
        if not repository:
            self.profile_image.set_model(Gtk.StringList.new(["Selecciona un repositorio válido"]))
            self.profile_select.set_model(Gtk.StringList.new(["No hay perfiles disponibles"]))
            return
        repository_id = repository["id"]
        self.api.submit(
            "repository_images", {"repository_id": repository_id},
            on_success=lambda result: self._populate_profile_images(result)
            if page_generation == self._page_generation and generation == self._profile_repository_generation else None,
            on_error=lambda error: self._profile_failed(error, page_generation)
            if page_generation == self._page_generation and generation == self._profile_repository_generation else None,
        )
        self.api.submit(
            "restore_profiles", {"repository_id": repository_id},
            on_success=lambda result: self._populate_restore_profiles(result)
            if page_generation == self._page_generation and generation == self._profile_repository_generation else None,
            on_error=lambda error: self._profile_failed(error, page_generation)
            if page_generation == self._page_generation and generation == self._profile_repository_generation else None,
        )

    def _populate_profile_images(self, result: dict[str, Any]) -> None:
        self.profile_images = [item for item in result.get("images", []) if isinstance(item, dict) and item.get("image_type") == "disk" and item.get("image_format") == "raw" and item.get("image_id")]
        labels = [str(item["image_id"]) + " · " + str(item.get("source_size_bytes", 0)) + " bytes" for item in self.profile_images]
        self.profile_image.set_model(Gtk.StringList.new(labels or ["No hay imágenes RAW de disco"]))
        self.profile_image.set_selected(0)

    def _populate_restore_profiles(self, result: dict[str, Any]) -> None:
        self.profile_records = [item for item in result.get("profiles", []) if isinstance(item, dict) and item.get("profile_id")]
        labels = [
            f"{item.get('profile_id')} · {item.get('name') or '—'} · {item.get('target_path') or 'Sin coincidencia'} · {'consumido' if item.get('consumed') else 'disponible'}"
            for item in self.profile_records
        ]
        self.profile_select.set_model(Gtk.StringList.new(labels or ["No hay perfiles guardados"]))
        self.profile_select.set_selected(0)
        self.profile_result.set_text(f"Perfiles persistidos: {len(self.profile_records)}. Son de un solo uso y no se ejecutan al crearlos.")

    def _create_restore_profile(self, _button: Gtk.Button) -> None:
        import datetime
        repository = self._selected_profile_repository()
        image_index, target_index = self.profile_image.get_selected(), self.profile_target.get_selected()
        if not repository or image_index >= len(getattr(self, "profile_images", [])) or target_index >= len(getattr(self, "profile_target_devices", [])):
            self.profile_result.set_text("Selecciona repositorio, imagen RAW y disco con identidad estable.")
            return
        target = self.profile_target_devices[target_index]
        name, expiry_text = self.profile_name.get_text().strip(), self.profile_expiry.get_text().strip()
        if not name or not expiry_text:
            self.profile_result.set_text("Indica nombre y caducidad del perfil.")
            return
        try:
            expiry = datetime.datetime.fromisoformat(expiry_text.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry.utcoffset() is None or expiry <= datetime.datetime.now(datetime.timezone.utc):
                raise ValueError("la fecha debe ser futura e incluir zona horaria")
        except ValueError as exc:
            self.profile_result.set_text("Caducidad ISO-8601 no válida: " + str(exc))
            return
        params = {
            "name": name, "image_id": self.profile_images[image_index]["image_id"],
            "target_wwn": target.get("wwn"), "target_serial": target.get("serial"),
            "expires_at": expiry.isoformat(), "repository_id": repository["id"],
        }
        self.profile_result.set_text("Guardando perfil; todavía no se arma ni ejecuta…")
        page_generation = self._profile_page_generation
        self._profile_create_generation = getattr(self, "_profile_create_generation", 0) + 1
        request_generation = self._profile_create_generation
        self.api.submit(
            "create_restore_profile", params,
            on_success=lambda result: self._restore_profile_created(result, page_generation, request_generation),
            on_error=lambda error: self._profile_failed(error, page_generation, request_generation, request_kind="create"),
        )

    def _restore_profile_created(self, result: dict[str, Any], page_generation: int | None = None, request_generation: int | None = None) -> None:
        if page_generation != self._page_generation or page_generation != getattr(self, "_profile_page_generation", None) or request_generation != getattr(self, "_profile_create_generation", None):
            return
        self.profile_result.set_text("Perfil guardado, no armado ni ejecutado: " + str(result.get("profile_id", "—")))
        self._load_restore_profiles_for_repository()

    def _execute_selected_restore_profile(self, _button: Gtk.Button) -> None:
        index = self.profile_select.get_selected()
        if index >= len(getattr(self, "profile_records", [])):
            self.profile_result.set_text("Selecciona un perfil guardado.")
            return
        profile = self.profile_records[index]
        target = profile.get("target_path")
        expected = "ERASE " + target if target else ""
        if profile.get("consumed") or not target or self.profile_confirmation.get_text() != expected:
            self.profile_result.set_text("El perfil debe estar disponible y el disco detectado debe confirmarse exactamente: " + expected)
            return
        repository = self._selected_profile_repository()
        if not repository:
            self.profile_result.set_text("Selecciona el repositorio persistente del perfil.")
            return
        params = {"profile_id": profile["profile_id"], "target": target, "confirmation": expected, "repository_id": repository["id"]}
        self.profile_result.set_text("Solicitando ejecución del perfil de un solo uso…")
        page_generation = self._profile_page_generation
        profile_id = profile["profile_id"]
        self._profile_execute_generation = getattr(self, "_profile_execute_generation", 0) + 1
        request_generation = self._profile_execute_generation
        self.api.submit(
            "execute_restore_profile", params,
            on_success=lambda result: self._restore_profile_operation_accepted(result, page_generation, request_generation, profile_id),
            on_error=lambda error: self._profile_failed(error, page_generation, request_generation, request_kind="execute"),
        )

    def _restore_profile_operation_accepted(self, result: dict[str, Any], page_generation: int | None = None, request_generation: int | None = None, profile_id: str | None = None) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self._profile_failed(RuntimeError("El backend no devolvió operation_id."), page_generation, request_generation, request_kind="execute")
            return
        self._profile_operation_results = getattr(self, "_profile_operation_results", {})
        self._profile_operation_results[operation_id] = {"profile_id": profile_id, "accepted": result}
        request_is_current = request_generation == getattr(self, "_profile_execute_generation", None)
        if request_is_current:
            self._latest_profile_operation_id = operation_id
        if page_generation != self._page_generation or page_generation != getattr(self, "_profile_page_generation", None) or not request_is_current:
            return
        self.profile_operation_id = operation_id
        self.profile_cancel.set_sensitive(True)
        self.profile_result.set_text("Restauración aceptada por el worker duradero: " + operation_id)
        GLib.timeout_add_seconds(1, lambda: self._poll_restore_profile_operation(operation_id, page_generation))

    def _poll_restore_profile_operation(self, operation_id: str | None = None, page_generation: int | None = None) -> bool:
        operation_id = operation_id or getattr(self, "profile_operation_id", None)
        if not operation_id:
            return GLib.SOURCE_REMOVE
        self.api.submit("local_operation_status", {"operation_id": operation_id}, on_success=lambda status: self._show_restore_profile_operation_status(status, operation_id, page_generation), on_error=lambda error: self._profile_operation_status_failed(error, operation_id, page_generation))
        return GLib.SOURCE_REMOVE

    def _show_restore_profile_operation_status(self, status: dict[str, Any], operation_id: str | None = None, page_generation: int | None = None) -> None:
        operation_id = operation_id or status.get("operation_id")
        self._profile_operation_results = getattr(self, "_profile_operation_results", {})
        self._profile_operation_results.setdefault(operation_id, {})["status"] = status
        if page_generation != self._page_generation or page_generation != getattr(self, "_profile_page_generation", None) or operation_id != getattr(self, "profile_operation_id", None):
            return
        state = status.get("state", "unknown")
        events = status.get("events") or []
        self.profile_result.set_text("Restauración " + str(operation_id) + ": " + str(state))
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            terminal = events[-1].get("details", {}) if events else {}
            self.profile_result.set_text("Restauración " + str(state) + ": " + str(terminal.get("error") or terminal.get("reason") or terminal))
            self.profile_cancel.set_sensitive(False)
            self.profile_operation_id = None
            if getattr(self, "_latest_profile_operation_id", None) == operation_id:
                self._latest_profile_operation_id = None
            self.profile_confirmation.set_text("")
            self._load_restore_profiles_for_repository()
        else:
            GLib.timeout_add_seconds(2, lambda: self._poll_restore_profile_operation(operation_id, page_generation))

    def _profile_operation_status_failed(self, error: Exception, operation_id: str | None = None, page_generation: int | None = None) -> None:
        self._profile_operation_errors = getattr(self, "_profile_operation_errors", {})
        if operation_id:
            self._profile_operation_errors[operation_id] = str(error)
        if page_generation != self._page_generation or page_generation != getattr(self, "_profile_page_generation", None) or operation_id != getattr(self, "profile_operation_id", None):
            return
        self.profile_result.set_text("No se pudo consultar el estado; conserva el ID del trabajo: " + str(error))
        GLib.timeout_add_seconds(5, lambda: self._poll_restore_profile_operation(operation_id, page_generation))

    def _cancel_restore_profile_operation(self, _button: Gtk.Button) -> None:
        operation_id = getattr(self, "profile_operation_id", None)
        if operation_id:
            self.profile_cancel.set_sensitive(False)
            page_generation = self._profile_page_generation
            self.api.submit("cancel_local_operation", {"operation_id": operation_id}, on_success=lambda _result: None, on_error=lambda error: self._profile_failed(error, page_generation, operation_id=operation_id))

    def _profile_failed(
        self, error: Exception, page_generation: int | None = None,
        request_generation: int | None = None, operation_id: str | None = None,
        request_kind: str | None = None,
    ) -> None:
        self._profile_action_errors = getattr(self, "_profile_action_errors", {})
        key = operation_id or (f"request:{request_generation}" if request_generation is not None else "latest")
        self._profile_action_errors[key] = str(error)
        if page_generation is None:
            page_generation = getattr(self, "_profile_page_generation", None)
        if page_generation != self._page_generation or page_generation != getattr(self, "_profile_page_generation", None):
            return
        if operation_id is not None and operation_id != getattr(self, "profile_operation_id", None):
            return
        if request_generation is not None:
            current = getattr(self, "_profile_create_generation" if request_kind == "create" else "_profile_execute_generation", None)
            if request_generation != current:
                return
        if hasattr(self, "profile_result"):
            self.profile_result.set_text("Operación de perfil fallida: " + str(error))

    def _show_images_page(self) -> None:
        self._image_page_generation = getattr(self, "_image_page_generation", 0) + 1
        page_generation = self._image_page_generation
        window_generation = self._page_generation
        self._image_window_page_generation = window_generation
        self._image_catalog_generation = getattr(self, "_image_catalog_generation", 0) + 1
        self._image_browse_generation = getattr(self, "_image_browse_generation", 0) + 1
        self.image_catalog = []
        self.image_layout = None
        self.image_session_id = ""
        self.page_description.set_text("Inspección verificada de imágenes de disco, exploración de archivos y extracción de particiones.")

        def add_image_row(group: Adw.PreferencesGroup, title: str, widget: Gtk.Widget, subtitle: str = "") -> Adw.ActionRow:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.add_suffix(widget)
            row.set_activatable_widget(widget)
            group.add(row)
            return row

        catalog_group = Adw.PreferencesGroup(
            title="Repositorio e imagen",
            description="Selecciona el repositorio y una imagen de disco disponible.",
        )
        self.page_body.append(catalog_group)
        self.image_repository = Gtk.DropDown.new_from_strings(["Cargando repositorios…"])
        add_image_row(catalog_group, "Repositorio", self.image_repository)
        self.image_select = Gtk.DropDown.new_from_strings(["Cargando imágenes de disco…"])
        add_image_row(catalog_group, "Imagen de disco", self.image_select)
        self.image_catalog_stack = Gtk.Stack()
        self.image_catalog_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.image_catalog_stack.add_named(self.image_select, "images")
        self.image_catalog_empty = Adw.StatusPage(
            title="No hay imágenes de disco",
            description="Este repositorio todavía no contiene imágenes de disco inspeccionables.",
            icon_name="drive-harddisk-symbolic",
        )
        self.image_catalog_stack.add_named(self.image_catalog_empty, "empty")
        self.image_catalog_loading = Adw.StatusPage(
            title="Cargando catálogo",
            description="Consultando las imágenes disponibles en el repositorio seleccionado.",
            icon_name="content-loading-symbolic",
        )
        self.image_catalog_stack.add_named(self.image_catalog_loading, "loading")
        self.image_catalog_error = Adw.StatusPage(
            title="No se pudo cargar el catálogo",
            description="Comprueba el repositorio y vuelve a seleccionarlo para reintentar.",
            icon_name="dialog-error-symbolic",
        )
        self.image_catalog_stack.add_named(self.image_catalog_error, "error")
        self.image_catalog_stack.set_visible_child_name("loading")
        catalog_group.add(self.image_catalog_stack)

        inspect_group = Adw.PreferencesGroup(
            title="Inspección y verificación",
            description="Verifica el manifiesto, la tabla de particiones y los hashes de la imagen.",
        )
        self.page_body.append(inspect_group)
        inspect = Gtk.Button(label="Inspeccionar tabla de particiones")
        add_image_row(inspect_group, "Inspección de estructura", inspect)
        inspect.connect("clicked", self._inspect_selected_image)
        self.image_partition = Gtk.DropDown.new_from_strings(["Inspecciona primero la imagen…"])
        add_image_row(inspect_group, "Partición", self.image_partition)
        verify = Gtk.Button(label="Verificar integridad completa")
        add_image_row(inspect_group, "Verificación de integridad", verify)
        verify.connect("clicked", self._verify_selected_image)

        browse_group = Adw.PreferencesGroup(
            title="Exploración y descarga",
            description="Explora el filesystem de una partición verificada y guarda archivos en ~/Downloads.",
        )
        self.page_body.append(browse_group)
        self.image_browse_path = Gtk.Entry()
        self.image_browse_path.set_text("/")
        add_image_row(browse_group, "Ruta dentro del filesystem", self.image_browse_path)
        browse = Gtk.Button(label="Explorar directorio")
        add_image_row(browse_group, "Exploración", browse)
        browse.connect("clicked", self._browse_selected_image)
        self.image_download_path = Gtk.Entry()
        self.image_download_path.set_placeholder_text("/ruta/al/archivo")
        add_image_row(browse_group, "Archivo de origen (ruta absoluta)", self.image_download_path)
        download = Gtk.Button(label="Descargar en ~/Downloads")
        add_image_row(browse_group, "Descarga segura", download)
        download.connect("clicked", self._download_selected_image_file)

        extraction_group = Adw.PreferencesGroup(
            title="Extracción de particiones",
            description="Extrae una partición como imagen en un repositorio montado, verificado y escribible.",
        )
        self.page_body.append(extraction_group)
        extract = Gtk.Button(label="Extraer partición como imagen")
        add_image_row(extraction_group, "Iniciar extracción", extract)
        extract.connect("clicked", self._extract_selected_partition)
        self.image_cancel = Gtk.Button(label="Cancelar extracción")
        self.image_cancel.set_sensitive(False)
        add_image_row(extraction_group, "Cancelación", self.image_cancel)
        self.image_cancel.connect("clicked", self._cancel_image_extraction)

        result_group = Adw.PreferencesGroup(
            title="Resultado y actividad",
            description="Estado de las operaciones y contenido del directorio inspeccionado.",
        )
        self.page_body.append(result_group)
        self.image_result = Gtk.Label(label="", xalign=0)
        self.image_result.set_wrap(True)
        self.image_result.set_selectable(True)
        result_row = Adw.ActionRow(title="Estado de la operación")
        result_row.add_suffix(self.image_result)
        result_group.add(result_row)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.image_listing = Gtk.Label(label="", xalign=0, yalign=0)
        self.image_listing.set_selectable(True)
        self.image_listing.set_wrap(True)
        scroller.set_child(self.image_listing)
        result_group.add(scroller)

        self.image_select.connect("notify::selected", self._image_selection_changed)
        self.image_partition.connect("notify::selected", self._image_partition_changed)
        self._image_remote_repositories = None
        self._image_s3_repositories = None
        self.api.submit(
            "remote_repositories",
            on_success=lambda result: self._populate_image_repositories(result)
            if page_generation == self._image_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error: self._image_page_failed(error, page_generation, window_generation)
            if page_generation == self._image_page_generation and window_generation == self._page_generation else None,
        )
        self.api.submit(
            "s3_repositories",
            on_success=lambda result: self._populate_image_s3_repositories(result)
            if page_generation == self._image_page_generation and window_generation == self._page_generation else None,
            on_error=lambda error: self._image_page_failed(error, page_generation, window_generation)
            if page_generation == self._image_page_generation and window_generation == self._page_generation else None,
        )
        pending_operation_id = getattr(self, "_latest_image_operation_id", None)
        if pending_operation_id:
            self.image_operation_id = pending_operation_id
            self.image_cancel.set_sensitive(True)
            self.image_result.set_text("Recuperando seguimiento de extracción " + pending_operation_id + "…")
            self._poll_image_extraction(pending_operation_id, page_generation, window_generation)

    def _populate_image_repositories(self, result: dict[str, Any]) -> None:
        self._image_remote_repositories = [
            {**item, "_repository_kind": "remote"}
            for item in result.get("repositories", [])
            if isinstance(item, dict) and item.get("id") and item.get("mounted") and item.get("verified")
        ]
        self._finish_image_repository_loading()

    def _populate_image_s3_repositories(self, result: dict[str, Any]) -> None:
        self._image_s3_repositories = [
            {**item, "_repository_kind": "s3"}
            for item in result.get("repositories", [])
            if isinstance(item, dict) and item.get("id")
        ]
        self._finish_image_repository_loading()

    def _finish_image_repository_loading(self) -> None:
        if self._image_remote_repositories is None or self._image_s3_repositories is None:
            return
        self.image_repositories = self._image_remote_repositories + self._image_s3_repositories
        labels = [
            str(item.get("id")) + (" · S3" if item.get("_repository_kind") == "s3" else " · " + str(item.get("provider")))
            + (" · solo lectura" if item.get("read_only") else "")
            for item in self.image_repositories
        ]
        self.image_repository.set_model(Gtk.StringList.new(["Repositorio local"] + labels))
        self.image_repository.set_selected(0)
        self.image_repository.connect("notify::selected", self._image_repository_changed)
        self._load_image_catalog()

    def _image_repository_id(self) -> str | None:
        index = self.image_repository.get_selected()
        if index > 0 and index - 1 < len(getattr(self, "image_repositories", [])):
            return self.image_repositories[index - 1].get("id")
        return None

    def _image_repository_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._load_image_catalog()

    def _load_image_catalog(self) -> None:
        self._image_catalog_generation = getattr(self, "_image_catalog_generation", 0) + 1
        generation = self._image_catalog_generation
        page_generation = self._image_page_generation
        window_generation = self._image_window_page_generation
        self.image_catalog = []
        self.image_select.set_model(Gtk.StringList.new(["Cargando imágenes…"]))
        self.image_select.set_selected(0)
        self._reset_image_layout()
        self.image_catalog_stack.set_visible_child_name("loading")
        repository_id = self._image_repository_id()
        if repository_id:
            self.api.submit(
                "repository_images", {"repository_id": repository_id},
                on_success=lambda result: self._populate_image_catalog(result)
                if page_generation == self._image_page_generation and window_generation == self._page_generation and generation == self._image_catalog_generation else None,
                on_error=lambda error: self._image_page_failed(error, page_generation, window_generation)
                if page_generation == self._image_page_generation and window_generation == self._page_generation and generation == self._image_catalog_generation else None,
            )
        else:
            self.api.submit(
                "images",
                on_success=lambda result: self._populate_image_catalog(result)
                if page_generation == self._image_page_generation and window_generation == self._page_generation and generation == self._image_catalog_generation else None,
                on_error=lambda error: self._image_page_failed(error, page_generation, window_generation)
                if page_generation == self._image_page_generation and window_generation == self._page_generation and generation == self._image_catalog_generation else None,
            )

    def _populate_image_catalog(self, result: dict[str, Any]) -> None:
        self.image_catalog = [item for item in result.get("images", []) if isinstance(item, dict) and item.get("image_type") == "disk" and item.get("image_id")]
        labels = [str(item["image_id"]) + " · " + str(item.get("source_size_bytes", 0)) + " bytes" for item in self.image_catalog]
        self.image_select.set_model(Gtk.StringList.new(labels or []))
        self.image_select.set_selected(0)
        self.image_catalog_stack.set_visible_child_name("images" if self.image_catalog else "empty")
        self._reset_image_layout()

    def _image_selection_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._reset_image_layout()

    def _reset_image_layout(self) -> None:
        self._image_browse_generation = getattr(self, "_image_browse_generation", 0) + 1
        self.image_layout = None
        self.image_session_id = ""
        self.image_partition.set_model(Gtk.StringList.new(["Inspecciona primero la imagen…"]))
        self.image_partition.set_selected(0)
        self.image_listing.set_text("")
        self.image_result.set_text("")

    def _selected_image(self) -> dict[str, Any] | None:
        index = self.image_select.get_selected()
        return self.image_catalog[index] if index < len(getattr(self, "image_catalog", [])) else None

    def _verify_selected_image(self, _button: Gtk.Button) -> None:
        image = self._selected_image()
        if not image:
            self.image_result.set_text("Selecciona una imagen de disco.")
            return
        params = {"image_id": image["image_id"]}
        repository_id = self._image_repository_id()
        if repository_id:
            params["repository_id"] = repository_id
        self.image_result.set_text("Verificando todos los artefactos y sus hashes…")
        self._image_verification_generation = getattr(self, "_image_verification_generation", 0) + 1
        request_generation = self._image_verification_generation
        page_generation = self._image_page_generation
        window_generation = self._image_window_page_generation
        catalog_generation = self._image_catalog_generation
        image_id = image["image_id"]
        self.api.submit(
            "verify_image", params,
            on_success=lambda result: self._show_image_verification(result, image_id, repository_id, page_generation, window_generation, catalog_generation, request_generation),
            on_error=lambda error: self._image_page_failed(error, page_generation, window_generation)
            if self._image_view_is_current(page_generation, window_generation, catalog_generation) and request_generation == self._image_verification_generation else None,
        )

    def _show_image_verification(
        self, result: dict[str, Any], image_id: str | None = None,
        repository_id: str | None = None, page_generation: int | None = None,
        window_generation: int | None = None, catalog_generation: int | None = None,
        request_generation: int | None = None,
    ) -> None:
        self._image_verification_results = getattr(self, "_image_verification_results", {})
        self._image_verification_results[(repository_id, image_id)] = result
        if (
            not self._image_view_is_current(page_generation, window_generation, catalog_generation)
            or request_generation != self._image_verification_generation
            or (self._selected_image() or {}).get("image_id") != image_id
            or self._image_repository_id() != repository_id
        ):
            return
        import json
        self.image_result.set_text("Resultado de verificación: " + json.dumps(result, ensure_ascii=False))

    def _inspect_selected_image(self, _button: Gtk.Button) -> None:
        image = self._selected_image()
        if not image:
            self.image_result.set_text("Selecciona una imagen de disco.")
            return
        params = {"image_id": image["image_id"]}
        repository_id = self._image_repository_id()
        if repository_id:
            params["repository_id"] = repository_id
        page_generation = self._image_page_generation
        window_generation = self._image_window_page_generation
        catalog_generation = self._image_catalog_generation
        self._image_inspection_generation = getattr(self, "_image_inspection_generation", 0) + 1
        request_generation = self._image_inspection_generation
        image_id = image["image_id"]
        self.image_result.set_text("Verificando manifiesto y tabla de particiones…")
        self.api.submit(
            "inspect_image_layout", params,
            on_success=lambda layout: self._show_image_layout(layout, image_id, repository_id, page_generation, window_generation, catalog_generation, request_generation),
            on_error=lambda error: self._image_page_failed(error, page_generation, window_generation)
            if self._image_view_is_current(page_generation, window_generation, catalog_generation) and request_generation == self._image_inspection_generation else None,
        )

    def _show_image_layout(
        self, layout: dict[str, Any], image_id: str | None = None,
        repository_id: str | None = None, page_generation: int | None = None,
        window_generation: int | None = None, catalog_generation: int | None = None,
        request_generation: int | None = None,
    ) -> None:
        self._image_inspection_results = getattr(self, "_image_inspection_results", {})
        self._image_inspection_results[(repository_id, image_id)] = layout
        image = self._selected_image()
        if (
            not self._image_view_is_current(page_generation, window_generation, catalog_generation)
            or request_generation != self._image_inspection_generation
            or not image or image.get("image_id") != image_id
            or self._image_repository_id() != repository_id
            or layout.get("image_id") != image_id
        ):
            return
        self.image_layout = layout
        partitions = layout.get("partitions") or []
        labels = ["Selecciona una partición…"] + [
            f"{item.get('node')} · {item.get('uuid') or item.get('name') or item.get('selector')} · {item.get('size_bytes', 0)} bytes"
            for item in partitions if item.get("selector")
        ]
        self.image_partition.set_model(Gtk.StringList.new(labels))
        self.image_partition.set_selected(0)
        self.image_result.set_text(f"{layout.get('message', 'Tabla verificada')} · {len(partitions)} particiones · {layout.get('source_size_bytes', 0)} bytes · sector lógico {layout.get('logical_sector_size', '—')} bytes")

    def _selected_image_partition(self) -> tuple[dict[str, Any], int, str]:
        image = self._selected_image()
        layout = getattr(self, "image_layout", None)
        index = self.image_partition.get_selected()
        if not image or not layout or layout.get("image_id") != image["image_id"]:
            raise ValueError("Inspecciona la imagen de disco seleccionada antes de continuar.")
        if index == 0 or index > len(layout.get("partitions", [])):
            raise ValueError("Selecciona una partición de la tabla verificada.")
        part = layout["partitions"][index - 1]
        return image, index, part["selector"]

    def _image_browse_params(self, download: bool = False) -> dict[str, Any]:
        image, index, _selector = self._selected_image_partition()
        params = {"image_id": image["image_id"], "partition_index": index, "path": self.image_browse_path.get_text().strip() or "/"}
        repository_id = self._image_repository_id()
        if repository_id:
            params["repository_id"] = repository_id
        if getattr(self, "image_session_id", ""):
            params["session_id"] = self.image_session_id
        if download:
            params["download"] = True
        return params

    def _browse_selected_image(self, _button: Gtk.Button) -> None:
        try:
            params = self._image_browse_params()
        except ValueError as exc:
            self.image_result.set_text(str(exc))
            return
        self._image_browse_generation = getattr(self, "_image_browse_generation", 0) + 1
        browse_generation = self._image_browse_generation
        page_generation = self._image_page_generation
        window_generation = self._image_window_page_generation
        catalog_generation = self._image_catalog_generation
        self.api.submit(
            "browse_image", params,
            on_success=lambda result: self._show_image_directory(result)
            if browse_generation == self._image_browse_generation
            and page_generation == self._image_page_generation
            and window_generation == self._page_generation
            and catalog_generation == self._image_catalog_generation else None,
            on_error=lambda error: self._image_browse_failed(error, page_generation, window_generation, catalog_generation, browse_generation),
        )

    def _image_browse_failed(
        self, error: Exception, page_generation: int, window_generation: int,
        catalog_generation: int, browse_generation: int,
    ) -> None:
        self._image_browse_errors = getattr(self, "_image_browse_errors", [])
        self._image_browse_errors.append(str(error))
        if (
            not self._image_view_is_current(page_generation, window_generation, catalog_generation)
            or browse_generation != self._image_browse_generation
        ):
            return
        self.image_session_id = ""
        self.image_listing.set_text("")
        self.image_result.set_text("No se pudo explorar la imagen: " + str(error))

    def _show_image_directory(self, result: dict[str, Any]) -> None:
        self.image_session_id = result.get("session_id", "")
        self.image_browse_path.set_text(result.get("path", "/"))
        entries = result.get("entries") or []
        self.image_listing.set_text("\n".join(
            f"{item.get('kind', '—'):9} {item.get('name', '—')} {item.get('size_bytes', '') if item.get('kind') == 'file' else ''}"
            for item in entries
        ) or "(directorio vacío)")
        self.image_result.set_text(f"{result.get('partition', '—')} · {result.get('filesystem', '—')} · {result.get('path', '/')}")

    def _download_selected_image_file(self, _button: Gtk.Button) -> None:
        path = self.image_download_path.get_text().strip()
        if not path.startswith("/") or "\x00" in path:
            self.image_result.set_text("Indica una ruta absoluta de archivo dentro de la imagen.")
            return
        try:
            params = self._image_browse_params(download=True)
            params["path"] = path
        except ValueError as exc:
            self.image_result.set_text(str(exc))
            return
        self._image_download_generation = getattr(self, "_image_download_generation", 0) + 1
        download_generation = self._image_download_generation
        page_generation = self._image_page_generation
        window_generation = self._image_window_page_generation
        catalog_generation = self._image_catalog_generation
        image_id = (self._selected_image() or {}).get("image_id")
        repository_id = self._image_repository_id()
        self.api.submit(
            "browse_image", params,
            on_success=lambda result: self._save_image_download(result, page_generation, window_generation, catalog_generation, download_generation, image_id, repository_id),
            on_error=lambda error: self._image_download_failed(error, page_generation, window_generation, catalog_generation, download_generation, image_id, repository_id),
        )

    def _image_download_is_current(
        self, page_generation: int, window_generation: int, catalog_generation: int,
        download_generation: int, image_id: str | None, repository_id: str | None,
    ) -> bool:
        return (
            self._image_view_is_current(page_generation, window_generation, catalog_generation)
            and download_generation == self._image_download_generation
            and (self._selected_image() or {}).get("image_id") == image_id
            and self._image_repository_id() == repository_id
        )

    def _image_download_failed(
        self, error: Exception, page_generation: int, window_generation: int,
        catalog_generation: int, download_generation: int,
        image_id: str | None, repository_id: str | None,
    ) -> None:
        self._image_download_errors = getattr(self, "_image_download_errors", [])
        self._image_download_errors.append(str(error))
        if self._image_download_is_current(page_generation, window_generation, catalog_generation, download_generation, image_id, repository_id):
            self.image_result.set_text("No se pudo descargar el archivo: " + str(error))

    def _save_image_download(
        self, result: dict[str, Any], page_generation: int | None = None,
        window_generation: int | None = None, catalog_generation: int | None = None,
        download_generation: int | None = None, image_id: str | None = None,
        repository_id: str | None = None,
    ) -> None:
        import base64
        filename, encoded = result.get("filename"), result.get("content_base64")
        if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(encoded, str):
            self._image_download_errors = getattr(self, "_image_download_errors", [])
            self._image_download_errors.append("El backend devolvió datos de descarga no válidos.")
            if self._image_download_is_current(page_generation, window_generation, catalog_generation, download_generation, image_id, repository_id):
                self.image_result.set_text("El backend devolvió datos de descarga no válidos.")
            return
        try:
            data = base64.b64decode(encoded, validate=True)
            download_dir = Path.home() / "Downloads"
            download_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            home = Path.home().resolve(strict=True)
            destination_dir = download_dir.resolve(strict=True)
            if not destination_dir.is_relative_to(home):
                raise ValueError("Downloads debe permanecer dentro del directorio personal.")
            destination = destination_dir / filename
            file_descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(file_descriptor, "wb") as stream:
                stream.write(data)
        except (OSError, ValueError) as exc:
            self._image_download_errors = getattr(self, "_image_download_errors", [])
            self._image_download_errors.append(str(exc))
            if self._image_download_is_current(page_generation, window_generation, catalog_generation, download_generation, image_id, repository_id):
                self.image_result.set_text(f"No se pudo guardar el archivo: {exc}")
            return
        self._image_download_results = getattr(self, "_image_download_results", [])
        self._image_download_results.append(str(destination))
        if self._image_download_is_current(page_generation, window_generation, catalog_generation, download_generation, image_id, repository_id):
            self.image_result.set_text(f"Archivo guardado: {destination}")

    def _image_view_is_current(self, page_generation: int | None, window_generation: int | None, catalog_generation: int | None = None) -> bool:
        return (
            page_generation == self._image_page_generation
            and window_generation == self._page_generation
            and (catalog_generation is None or catalog_generation == self._image_catalog_generation)
        )

    def _image_partition_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._image_browse_generation = getattr(self, "_image_browse_generation", 0) + 1
        self.image_session_id = ""
        self.image_listing.set_text("")

    def _extract_selected_partition(self, _button: Gtk.Button) -> None:
        try:
            image, _index, selector = self._selected_image_partition()
        except ValueError as exc:
            self.image_result.set_text(str(exc))
            return
        repository_id = self._image_repository_id()
        repository = next((item for item in getattr(self, "image_repositories", []) if item.get("id") == repository_id), None)
        if repository and repository.get("read_only"):
            self.image_result.set_text("La extracción no admite repositorios de solo lectura.")
            return
        if repository and repository.get("_repository_kind") == "remote" and (not repository.get("mounted") or not repository.get("verified")):
            self.image_result.set_text("La extracción en un repositorio de archivos requiere montaje e identidad verificados.")
            return
        params = {"image_id": image["image_id"], "selector": selector}
        if repository_id:
            params["repository_id"] = repository_id
        self.image_result.set_text("Solicitando extracción de partición…")
        self._image_action_generation = getattr(self, "_image_action_generation", 0) + 1
        request_generation = self._image_action_generation
        page_generation = self._image_page_generation
        window_generation = self._image_window_page_generation
        catalog_generation = self._image_catalog_generation
        self.api.submit(
            "extract_partition_image", params,
            on_success=lambda result: self._image_extraction_accepted(result, page_generation, window_generation, catalog_generation, request_generation),
            on_error=lambda error: self._image_page_failed(error, page_generation, window_generation),
        )

    def _image_extraction_accepted(self, result: dict[str, Any], page_generation: int | None = None, window_generation: int | None = None, catalog_generation: int | None = None, request_generation: int | None = None) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self._image_extraction_errors = getattr(self, "_image_extraction_errors", [])
            self._image_extraction_errors.append("El backend no devolvió operation_id.")
            if self._image_view_is_current(page_generation, window_generation, catalog_generation):
                self.image_result.set_text("El backend no devolvió operation_id.")
            return
        self._image_operation_results = getattr(self, "_image_operation_results", {})
        self._image_operation_results[operation_id] = {"accepted": result, "status": None}
        if request_generation == getattr(self, "_image_action_generation", None):
            self._latest_image_operation_id = operation_id
        if not self._image_view_is_current(page_generation, window_generation, catalog_generation) or request_generation != getattr(self, "_image_action_generation", None):
            return
        self.image_operation_id = operation_id
        self.image_cancel.set_sensitive(True)
        self.image_result.set_text("Extracción aceptada: " + operation_id)
        GLib.timeout_add_seconds(1, lambda: self._poll_image_extraction(operation_id, page_generation, window_generation))

    def _poll_image_extraction(self, operation_id: str | None = None, page_generation: int | None = None, window_generation: int | None = None) -> bool:
        operation_id = operation_id or getattr(self, "image_operation_id", None)
        if not operation_id:
            return GLib.SOURCE_REMOVE
        self.api.submit(
            "local_operation_status", {"operation_id": operation_id},
            on_success=lambda status: self._show_image_extraction_status(status, operation_id, page_generation, window_generation),
            on_error=lambda error: self._image_extraction_status_failed(error, operation_id, page_generation, window_generation),
        )
        return GLib.SOURCE_REMOVE

    def _show_image_extraction_status(self, status: dict[str, Any], operation_id: str | None = None, page_generation: int | None = None, window_generation: int | None = None) -> None:
        operation_id = operation_id or status.get("operation_id")
        self._image_operation_results = getattr(self, "_image_operation_results", {})
        self._image_operation_results.setdefault(operation_id, {})["status"] = status
        if not self._image_view_is_current(page_generation, window_generation) or operation_id != getattr(self, "image_operation_id", None):
            return
        events = status.get("events") or []
        event = next((item for item in reversed(events) if item.get("state") == "progress"), None)
        details = event.get("details", {}) if event else {}
        total, done = details.get("bytes_total"), details.get("bytes_done", 0)
        progress = f" · {round(done / total * 100, 1)}%" if isinstance(total, int) and total > 0 and isinstance(done, int) else ""
        state = status.get("state", "unknown")
        self.image_result.set_text(f"Extracción {operation_id}: {state}{progress}")
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            terminal = events[-1].get("details", {}) if events else {}
            self.image_result.set_text(f"Extracción {state}: {terminal.get('error') or terminal.get('reason') or terminal}")
            self.image_cancel.set_sensitive(False)
            self.image_operation_id = None
            if getattr(self, "_latest_image_operation_id", None) == operation_id:
                self._latest_image_operation_id = None
        else:
            GLib.timeout_add_seconds(2, lambda: self._poll_image_extraction(operation_id, page_generation, window_generation))

    def _image_extraction_status_failed(self, error: Exception, operation_id: str | None = None, page_generation: int | None = None, window_generation: int | None = None) -> None:
        self._image_extraction_errors = getattr(self, "_image_extraction_errors", [])
        self._image_extraction_errors.append(str(error))
        if not self._image_view_is_current(page_generation, window_generation) or operation_id != getattr(self, "image_operation_id", None):
            return
        self.image_result.set_text("No se pudo consultar el progreso; el trabajo conserva su ID: " + str(error))
        GLib.timeout_add_seconds(5, lambda: self._poll_image_extraction(operation_id, page_generation, window_generation))

    def _cancel_image_extraction(self, _button: Gtk.Button) -> None:
        operation_id = getattr(self, "image_operation_id", None)
        if operation_id:
            self.image_cancel.set_sensitive(False)
            page_generation = self._image_page_generation
            window_generation = self._image_window_page_generation
            self.api.submit("cancel_local_operation", {"operation_id": operation_id}, on_success=lambda _result: None, on_error=lambda error: self._image_cancel_failed(error, operation_id, page_generation, window_generation))

    def _image_cancel_failed(self, error: Exception, operation_id: str, page_generation: int, window_generation: int) -> None:
        self._image_cancel_errors = getattr(self, "_image_cancel_errors", {})
        self._image_cancel_errors[operation_id] = str(error)
        if self._image_view_is_current(page_generation, window_generation) and operation_id == getattr(self, "image_operation_id", None):
            self._image_page_failed(error, page_generation, window_generation)

    def _image_page_failed(self, error: Exception, page_generation: int | None = None, window_generation: int | None = None) -> None:
        self._image_page_errors = getattr(self, "_image_page_errors", [])
        self._image_page_errors.append(str(error))
        if page_generation is not None and not self._image_view_is_current(page_generation, window_generation):
            return
        if hasattr(self, "image_catalog_stack"):
            self.image_catalog_error.set_description(
                "No se pudo consultar el repositorio seleccionado. " + str(error)
            )
            self.image_catalog_stack.set_visible_child_name("error")
        if hasattr(self, "image_result"):
            self.image_result.set_text("Operación de imagen fallida: " + str(error))

    def _populate_capture_devices(self, inventory: dict[str, Any]) -> None:
        self.capture_inventory = inventory
        self.capture_inventory_devices = self._flatten_devices(inventory.get("devices"))
        self._capture_mode_changed(self.capture_kind, None)

    def _populate_capture_images(self, result: dict[str, Any]) -> None:
        self.capture_images = [item for item in result.get("images", []) if isinstance(item, dict) and item.get("image_id")]
        self._update_capture_image_options()

    def _update_capture_image_options(self) -> None:
        kind = self.capture_kind.get_selected()
        expected_type = {
            8: "disk", 9: "partition", 10: "logical_volume",
            13: "stratis_filesystem", 14: "disk", 15: "disk", 16: "disk",
        }.get(kind)
        previous_id = None
        current = getattr(self, "capture_selectable_images", [])
        selected = self.capture_image_select.get_selected()
        if selected < len(current):
            previous_id = current[selected].get("image_id")
        images = [
            item for item in getattr(self, "capture_images", [])
            if expected_type is not None and item.get("image_type") == expected_type
        ]
        self.capture_selectable_images = images
        labels = [
            str(item.get("image_id")) + " · " + str(item.get("image_type")) + " · "
            + str(item.get("source_size_bytes", 0)) + " bytes"
            for item in images
        ]
        self.capture_image_select.set_model(Gtk.StringList.new(labels or ["No hay imágenes compatibles"]))
        selected_index = next(
            (i for i, item in enumerate(images) if item.get("image_id") == previous_id), 0
        )
        self.capture_image_select.set_selected(selected_index)

    def _populate_capture_repositories(self, result: dict[str, Any]) -> None:
        self._capture_remote_repositories = [
            item for item in result.get("repositories", [])
            if isinstance(item, dict) and item.get("id") and item.get("mounted") and item.get("verified")
        ]
        self._finish_capture_repository_loading()

    def _populate_capture_s3_repositories(self, result: dict[str, Any]) -> None:
        self._capture_s3_repositories = [
            item for item in result.get("repositories", [])
            if isinstance(item, dict) and item.get("id")
        ]
        self._finish_capture_repository_loading()

    def _finish_capture_repository_loading(self) -> None:
        remote = getattr(self, "_capture_remote_repositories", None)
        s3 = getattr(self, "_capture_s3_repositories", None)
        if remote is None or s3 is None:
            return
        self.capture_repositories = [{"id": None, "_kind": "local"}] + [
            {**item, "_kind": "remote"} for item in remote
        ] + [{**item, "_kind": "s3"} for item in s3]
        labels = ["Repositorio local"] + [
            f'{item.get("id")} · {item.get("provider")} · montado y verificado'
            for item in remote
        ] + [
            f'{item.get("id")} · S3' + (" · solo lectura" if item.get("read_only") else "")
            for item in s3
        ]
        self.capture_repository.set_model(Gtk.StringList.new(labels))
        self.capture_repository.set_selected(0)
        self._capture_repository_changed(self.capture_repository, None)

    def _capture_repository_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._capture_catalog_generation = getattr(self, "_capture_catalog_generation", 0) + 1
        generation = self._capture_catalog_generation
        page_generation = self._capture_page_generation
        index = self.capture_repository.get_selected()
        repositories = getattr(self, "capture_repositories", [])
        self.capture_images = []
        self.capture_selectable_images = []
        self.capture_image_select.set_model(Gtk.StringList.new(["Cargando imágenes…"]))
        self.capture_image_select.set_selected(0)
        if index < len(repositories) and repositories[index].get("id"):
            self.api.submit(
                "repository_images", {"repository_id": repositories[index]["id"]},
                on_success=lambda response: self._populate_capture_images(response)
                if page_generation == self._page_generation and generation == self._capture_catalog_generation else None,
                on_error=lambda error: self._capture_failed(error)
                if page_generation == self._page_generation and generation == self._capture_catalog_generation else None,
            )
            return
        self.api.submit(
            "images",
            on_success=lambda response: self._populate_capture_images(response)
            if page_generation == self._page_generation and generation == self._capture_catalog_generation else None,
            on_error=lambda error: self._capture_failed(error)
            if page_generation == self._page_generation and generation == self._capture_catalog_generation else None,
        )

    def _capture_mode_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        kind = self.capture_kind.get_selected()
        self._update_capture_image_options()
        is_btrfs_capture = kind == 4
        is_btrfs_receive = kind == 5
        is_recovery = kind == 6
        is_finalize = kind == 7
        is_restore = kind in {8, 9, 10, 13, 16}
        is_proportional = kind == 16
        is_clone = kind in {11, 12}
        is_recovery_iso = kind == 14
        is_bundle = kind == 15
        is_image_build = is_recovery_iso or is_bundle
        source_visible = not (is_btrfs_capture or is_btrfs_receive or is_finalize or (is_restore and not is_proportional) or is_image_build)
        self.capture_source_label.set_visible(source_visible)
        self.capture_source.set_visible(source_visible)
        self.capture_target_label.set_visible(is_restore or is_clone)
        self.capture_target.set_visible(is_restore or is_clone)
        self.capture_image_select_label.set_visible(is_restore)
        self.capture_image_select.set_visible(is_restore)
        self.capture_confirmation_label.set_visible(is_restore or is_clone or is_recovery_iso)
        self.capture_confirmation.set_visible(is_restore or is_clone or is_recovery_iso)
        image_id_visible = not (is_restore or is_clone or is_image_build or is_finalize)
        self.capture_image_id_label.set_visible(image_id_visible)
        self.capture_image_id.set_visible(image_id_visible)
        self.capture_repository_label.set_visible(True)
        self.capture_base_iso_label.set_visible(is_image_build)
        self.capture_target_wwn_row.set_visible(is_recovery_iso)
        self.capture_target_serial_row.set_visible(is_recovery_iso)
        self.capture_bundle_name_label.set_visible(is_bundle)
        self.capture_deployment_job_label.set_visible(is_bundle)
        self.capture_image_select_label.set_visible(is_restore or is_image_build)
        self.capture_image_select.set_visible(is_restore or is_image_build)
        self.capture_btrfs_source_row.set_visible(is_btrfs_capture)
        self.capture_btrfs_parent_row.set_visible(is_btrfs_capture)
        self.capture_btrfs_target_row.set_visible(is_btrfs_receive)
        self.capture_btrfs_receive_parent_row.set_visible(is_btrfs_receive)
        self.capture_retry_row.set_visible(is_recovery)
        self.capture_resume_row.set_visible(is_recovery)
        if kind in {0, 6, 11, 16, 17}:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "disk" and isinstance(d.get("path"), str)]
            label = "Discos" if kind == 0 else "Discos para recuperación ddrescue" if kind == 6 else "Discos de origen para restauración proporcional" if kind == 16 else "Discos de origen P2V" if kind == 17 else "Discos de origen para clonación"
        elif kind in {1, 12}:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "part" and isinstance(d.get("path"), str)]
            label = "Particiones"
        elif kind in {2, 10}:
            self.capture_devices = self._flatten_logical_volumes(self.capture_inventory)
            label = "Volúmenes lógicos sanos"
        elif kind in {3, 13}:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "dm" and str(d.get("filesystem") or "").lower() == "xfs" and isinstance(d.get("path"), str)]
            label = "Filesystems Stratis XFS"
        elif kind in {4, 5}:
            self.capture_devices = []
            label = "Subvolúmenes Btrfs (ruta manual)"
        elif kind in {8, 9}:
            device_type = "disk" if kind == 8 else "part"
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == device_type and isinstance(d.get("path"), str)]
            label = "Destinos de restauración · " + ("discos" if kind == 8 else "particiones")
        elif kind in {14, 15}:
            self.capture_devices = []
            label = "Construcción de artefactos de recuperación y despliegue"
        else:
            self.capture_devices = []
            label = "Finalización de recuperación"
        labels = [str(d.get("path")) + " · " + str(d.get("model") or d.get("lvm_name") or d.get("type")) for d in self.capture_devices]
        self.capture_source.set_model(Gtk.StringList.new(labels or ["No hay dispositivos compatibles"]))
        self.capture_source.set_selected(0)
        target_type = "disk" if kind in {8, 11, 16} else "part"
        self.capture_target_devices = (self._flatten_logical_volumes(self.capture_inventory) if kind == 10 else [d for d in self.capture_inventory_devices if d.get("type") == "dm" and str(d.get("filesystem") or "").lower() == "xfs" and isinstance(d.get("path"), str)] if kind == 13 else [d for d in self.capture_inventory_devices if d.get("type") == target_type and isinstance(d.get("path"), str)])
        target_labels = [str(d.get("path")) + " · " + str(d.get("model") or d.get("type")) for d in self.capture_target_devices]
        self.capture_target.set_model(Gtk.StringList.new(target_labels or ["No hay destinos compatibles"]))
        self.capture_target.set_selected(0)
        self.capture_summary.set_text(label + " detectados: " + str(len(self.capture_devices)))
        self.capture_format_label.set_visible(kind == 0)
        self.capture_compression_row.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17})
        recipient_encryption_visible = kind in {0, 1, 2, 3, 4} and not (kind == 0 and self.capture_format.get_selected() == 1)
        passphrase_encryption_visible = kind == 0 and self.capture_format.get_selected() == 0
        self.capture_encrypt_row.set_visible(recipient_encryption_visible)
        self.capture_passphrase_toggle_row.set_visible(passphrase_encryption_visible)
        self.capture_passphrase_row.set_visible(passphrase_encryption_visible and self.capture_passphrase_toggle.get_active())
        self.capture_image_id_label.set_title("Identificador del stream Btrfs" if kind in {4, 5} else "ID del trabajo de recuperación" if kind == 7 else "ID de recuperación" if kind == 6 else "Identificador de imagen")
        self.capture_start.set_label("Recibir stream Btrfs" if kind == 5 else "Iniciar recuperación ddrescue" if kind == 6 else "Finalizar recuperación ddrescue" if kind == 7 else "Restaurar proporcionalmente" if is_proportional else "Capturar disco virtual QCOW2 (P2V)" if kind == 17 else "Iniciar restauración" if is_restore else "Iniciar clonación" if is_clone else "Construir ISO de recuperación" if is_recovery_iso else "Construir bundle de despliegue" if is_bundle else "Iniciar captura: " + label.lower())
        self._update_capture_confirmation_hint()

    def _update_capture_confirmation_hint(self, _widget: Gtk.DropDown | None = None, _pspec: Any = None) -> None:
        kind = self.capture_kind.get_selected()
        phrase = ""
        if kind == 14:
            index = self.capture_image_select.get_selected()
            images = getattr(self, "capture_selectable_images", [])
            if index < len(images):
                phrase = "BUILD " + str(images[index].get("image_id") or "")
        elif kind in {8, 9, 10, 11, 12, 13, 16}:
            target_index = self.capture_target.get_selected()
            targets = getattr(self, "capture_target_devices", [])
            if target_index < len(targets):
                target = str(targets[target_index].get("path") or "")
                if target:
                    phrase = "ERASE " + target
                    if kind == 12:
                        source_index = self.capture_source.get_selected()
                        sources = getattr(self, "capture_devices", [])
                        if source_index < len(sources):
                            source = str(sources[source_index].get("path") or "")
                            if source:
                                phrase += " FROM " + source
        self.capture_confirmation.set_placeholder_text(
            phrase if phrase else "Selecciona destino o imagen para ver la frase exacta"
        )

    def _capture_encryption_changed(self, widget: Gtk.CheckButton) -> None:
        if widget is self.capture_encrypt:
            if widget.get_active():
                self.capture_passphrase_toggle.set_active(False)
            self.capture_passphrase.set_text("")
        elif widget.get_active():
            self.capture_encrypt.set_active(False)
        else:
            self.capture_passphrase.set_text("")
        self._capture_mode_changed(self.capture_kind, None)

    def _flatten_logical_volumes(self, inventory: dict[str, Any]) -> list[dict[str, Any]]:
        groups = inventory.get("volume_topology", {}).get("volume_groups", [])
        volumes = [v for group in groups if group.get("status") == "healthy" for v in group.get("logical_volumes", [])]
        identity_counts: dict[str, int] = {}
        for volume in volumes:
            identity = volume.get("major_minor")
            if identity:
                identity_counts[identity] = identity_counts.get(identity, 0) + 1
        result = []
        for group in groups:
            if group.get("status") != "healthy":
                continue
            for volume in group.get("logical_volumes", []):
                identity, size = volume.get("major_minor"), volume.get("size_bytes")
                if volume.get("hidden") or volume.get("snapshot") or not identity or identity_counts.get(identity) != 1 or not isinstance(size, int) or size <= 0 or volume.get("health") not in (None, "", "-", "ok", "healthy"):
                    continue
                matches = [d for d in self.capture_inventory_devices if d.get("major_minor") == identity]
                if len(matches) == 1:
                    result.append({**matches[0], "path": volume.get("path"), "lvm_name": volume.get("name"), "size_bytes": size})
        return result

    def _start_disk_capture(self, _button: Gtk.Button) -> None:
        import re
        index = self.capture_source.get_selected()
        image_id = self.capture_image_id.get_text().strip()
        kind = self.capture_kind.get_selected()
        if kind in {14, 15}:
            image_index = self.capture_image_select.get_selected()
            repository_index = self.capture_repository.get_selected()
            if image_index >= len(getattr(self, "capture_selectable_images", [])) or repository_index >= len(getattr(self, "capture_repositories", [])):
                self.capture_result.set_text("Selecciona una imagen y un repositorio válidos.")
                return
            image = self.capture_selectable_images[image_index]
            repository = self.capture_repositories[repository_index]
            if image.get("image_type") != "disk":
                self.capture_result.set_text("La generación necesita una imagen de disco completo.")
                return
            if not repository.get("mounted") or not repository.get("verified") or repository.get("read_only"):
                self.capture_result.set_text("El repositorio debe estar montado, verificado y ser escribible.")
                return
            base_iso = self.capture_base_iso.get_text().strip()
            if not base_iso.startswith("/") or not base_iso.lower().endswith(".iso"):
                self.capture_result.set_text("Indica una ruta absoluta a un archivo .iso.")
                return
            params = {"image_id": image["image_id"], "repository_id": repository["id"]}
            if kind == 14:
                expected = "BUILD " + image["image_id"]
                if self.capture_confirmation.get_text() != expected:
                    self.capture_result.set_text("Escribe exactamente: " + expected)
                    return
                target_wwn = self.capture_target_wwn.get_text().strip() or None
                target_serial = self.capture_target_serial.get_text().strip() or None
                if not target_wwn and not target_serial:
                    self.capture_result.set_text("Indica el WWN y/o número de serie del destino autorizado.")
                    return
                params.update(base_iso_path=base_iso, target_wwn=target_wwn, target_serial=target_serial, confirm_build=expected)
                action = "build_recovery_iso"
            else:
                import json
                buffer = self.capture_deployment_job.get_buffer()
                job_text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
                try:
                    deployment_job = json.loads(job_text)
                except json.JSONDecodeError as exc:
                    self.capture_result.set_text("JSON DeploymentJob no válido: " + str(exc))
                    return
                if not isinstance(deployment_job, dict):
                    self.capture_result.set_text("DeploymentJob debe ser un objeto JSON.")
                    return
                bundle_name = self.capture_bundle_name.get_text().strip()
                if not bundle_name:
                    self.capture_result.set_text("Indica un nombre de bundle.")
                    return
                params.update(base_iso_path=base_iso, bundle_name=bundle_name, deployment_job=deployment_job)
                action = "build_deployment_bundle"
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando generación…")
            self._submit_capture_operation(action, params)
            return
        if kind in {8, 9, 10, 11, 12, 13, 16}:
            target_index = self.capture_target.get_selected()
            if target_index >= len(getattr(self, "capture_target_devices", [])):
                self.capture_result.set_text("Selecciona un destino compatible.")
                return
            target = self.capture_target_devices[target_index].get("path")
            confirmation = self.capture_confirmation.get_text()
            if kind in {11, 12}:
                if index >= len(getattr(self, "capture_devices", [])) or self.capture_devices[index].get("path") == target:
                    self.capture_result.set_text("Selecciona dos dispositivos distintos.")
                    return
                source = self.capture_devices[index]["path"]
                expected = "ERASE " + target if kind == 11 else "ERASE " + target + " FROM " + source
                action = "clone_disk" if kind == 11 else "clone_partition"
                params = {"source": source, "target": target, "confirmation": confirmation}
            else:
                image_index = self.capture_image_select.get_selected()
                if image_index >= len(getattr(self, "capture_selectable_images", [])):
                    self.capture_result.set_text("Selecciona una imagen compatible.")
                    return
                image = self.capture_selectable_images[image_index]
                expected_type = {8: "disk", 9: "partition", 10: "logical_volume", 13: "stratis_filesystem", 16: "disk"}[kind]
                if image.get("image_type") != expected_type:
                    self.capture_result.set_text("La imagen seleccionada no corresponde al tipo de restauración.")
                    return
                expected = "ERASE " + target
                action = {8: "restore_disk", 9: "restore_partition", 10: "restore_logical_volume", 13: "restore_stratis_filesystem", 16: "restore_proportional_disk"}[kind]
                params = {"image_id": image["image_id"], "target": target, "confirmation": confirmation}
                if kind == 16:
                    if index >= len(getattr(self, "capture_devices", [])):
                        self.capture_result.set_text("Selecciona el disco de origen de referencia.")
                        return
                    source_device = self.capture_devices[index]
                    target_device = self.capture_target_devices[target_index]
                    if not source_device.get("major_minor") or not target_device.get("major_minor"):
                        self.capture_result.set_text("Actualiza el inventario: ambos discos necesitan identidad major:minor.")
                        return
                    if not isinstance(source_device.get("size_bytes"), int) or not isinstance(target_device.get("size_bytes"), int) or target_device["size_bytes"] >= source_device["size_bytes"]:
                        self.capture_result.set_text("El destino debe ser estrictamente menor que el disco de origen de referencia.")
                        return
                    params.update(source=source_device["path"], source_major_minor=source_device["major_minor"], target_major_minor=target_device["major_minor"])
                repository_index = self.capture_repository.get_selected()
                if repository_index < len(getattr(self, "capture_repositories", [])):
                    selected_repository = self.capture_repositories[repository_index]
                    if selected_repository.get("id"):
                        params["repository_id"] = selected_repository["id"]
            if confirmation != expected:
                self.capture_result.set_text("Escribe exactamente: " + expected)
                return
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando operación destructiva…")
            self._submit_capture_operation(action, params, passphrase=capture_passphrase)
            return
        if kind == 7:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Indica un identificador válido del trabajo de recuperación.")
                return
            params = {"job_id": image_id}
            repository_index = self.capture_repository.get_selected()
            if repository_index < len(getattr(self, "capture_repositories", [])):
                selected_repository = self.capture_repositories[repository_index]
                if selected_repository.get("id"):
                    params["repository_id"] = selected_repository["id"]
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando finalización de recuperación…")
            self._submit_capture_operation("finalize_recovery", params)
            return
        if kind == 6:
            if index >= len(getattr(self, "capture_devices", [])) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Selecciona un disco completo e indica un ID de recuperación válido.")
                return
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id, "retry_passes": 3, "resume": self.capture_resume.get_active()}
            repository_index = self.capture_repository.get_selected()
            if repository_index < len(getattr(self, "capture_repositories", [])):
                selected_repository = self.capture_repositories[repository_index]
                if selected_repository.get("id"):
                    params["repository_id"] = selected_repository["id"]
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando recuperación ddrescue…")
            self._submit_capture_operation("recover_disk", params)
            return
        if kind == 5:
            target_directory = self.capture_btrfs_target.get_text().strip()
            parent_path = self.capture_btrfs_receive_parent.get_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id) or not target_directory.startswith("/") or (parent_path and not parent_path.startswith("/")):
                self.capture_result.set_text("Indica el identificador del stream y un directorio destino absoluto; el padre, si se indica, también debe ser absoluto.")
                return
            params = {"image_id": image_id, "target_directory": target_directory}
            if parent_path:
                params["parent_path"] = parent_path
            repository_index = self.capture_repository.get_selected()
            if repository_index < len(getattr(self, "capture_repositories", [])):
                selected_repository = self.capture_repositories[repository_index]
                if selected_repository.get("id"):
                    params["repository_id"] = selected_repository["id"]
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando recepción Btrfs…")
            self._submit_capture_operation("receive_btrfs_subvolume", params)
            return
        if kind == 4:
            source_path = self.capture_btrfs_source.get_text().strip()
            parent_path = self.capture_btrfs_parent.get_text().strip()
            import re
            if not source_path.startswith("/") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Indica una ruta absoluta de subvolumen Btrfs y un identificador de stream válido.")
                return
            if parent_path and not parent_path.startswith("/") :
                self.capture_result.set_text("La ruta del padre incremental debe ser absoluta.")
                return
            params = {"source_path": source_path, "image_id": image_id, "compression": ("zstd", "lz4", "gzip", "xz", "none")[self.capture_compression.get_selected()], "encrypt": self.capture_encrypt.get_active()}
            if parent_path:
                params["parent_path"] = parent_path
            repository_index = self.capture_repository.get_selected()
            if repository_index < len(getattr(self, "capture_repositories", [])):
                selected_repository = self.capture_repositories[repository_index]
                if selected_repository.get("id"):
                    params["repository_id"] = selected_repository["id"]
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando captura Btrfs…")
            self._submit_capture_operation("capture_btrfs_subvolume", params)
            return
        if kind == 17:
            if index >= len(getattr(self, "capture_devices", [])) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Selecciona un disco de origen e indica un identificador de imagen válido.")
                return
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id}
            repository_index = self.capture_repository.get_selected()
            if repository_index < len(getattr(self, "capture_repositories", [])):
                repository = self.capture_repositories[repository_index]
                if repository.get("id"):
                    params["repository_id"] = repository["id"]
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando captura P2V…")
            self._submit_capture_operation("capture_p2v", params)
            return
        if index >= len(getattr(self, "capture_devices", [])):
            self.capture_result.set_text("Selecciona un disco de origen válido.")
            return
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
            self.capture_result.set_text("Identificador no válido.")
            return
        qcow2 = self.capture_kind.get_selected() == 0 and self.capture_format.get_selected() == 1
        compression = ("zstd", "lz4", "gzip", "xz", "none")[self.capture_compression.get_selected()]
        kind = self.capture_kind.get_selected()
        if kind == 0:
            passphrase_encryption = self.capture_passphrase_toggle.get_active() and not qcow2
            params = {
                "source": self.capture_devices[index]["path"], "image_id": image_id,
                "image_format": "qcow2" if qcow2 else "raw",
                "compression": "none" if qcow2 else compression,
                "encrypt": (self.capture_encrypt.get_active() or passphrase_encryption) and not qcow2,
            }
            action = "capture_disk"
        elif kind == 1:
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id, "partition_id": image_id, "compression": compression, "encrypt": self.capture_encrypt.get_active()}
            action = "capture_partition"
        elif kind == 2:
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id, "compression": compression, "encrypt": self.capture_encrypt.get_active()}
            action = "capture_logical_volume"
        else:
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id, "compression": compression, "encrypt": self.capture_encrypt.get_active()}
            action = "capture_stratis_filesystem"
        repository_index = self.capture_repository.get_selected()
        if repository_index < len(getattr(self, "capture_repositories", [])):
            selected_repository = self.capture_repositories[repository_index]
            if selected_repository.get("id"):
                params["repository_id"] = selected_repository["id"]
        capture_passphrase = ""
        if kind == 0 and not qcow2 and self.capture_passphrase_toggle.get_active():
            capture_passphrase = self.capture_passphrase.get_text()
            if not capture_passphrase:
                self.capture_result.set_text("Indica una frase secreta para cifrar la captura RAW.")
                return
            params["encrypt_passphrase"] = True
        self.capture_start.set_sensitive(False)
        self.capture_result.set_text("Solicitando captura…")
        self._submit_capture_operation(action, params, passphrase=capture_passphrase)

    def _submit_capture_operation(self, action: str, params: dict[str, Any], passphrase: str = "") -> None:
        self._capture_request_generation = getattr(self, "_capture_request_generation", 0) + 1
        request_generation = self._capture_request_generation
        page_generation = self._capture_page_generation
        self._capture_requests = getattr(self, "_capture_requests", {})
        self._capture_requests[request_generation] = {
            "page_generation": page_generation,
            "passphrase": passphrase,
            "action": action,
        }
        self.api.submit(
            action,
            params,
            on_success=lambda result: self._capture_accepted(
                result, page_generation, request_generation, passphrase
            ),
            on_error=lambda error: self._capture_failed(error, page_generation, request_generation),
        )

    def _capture_view_is_current(self, page_generation: int, operation_id: str | None = None) -> bool:
        if page_generation != self._page_generation or page_generation != getattr(self, "_capture_page_generation", None):
            return False
        if operation_id is not None and getattr(self, "active_capture_id", None) != operation_id:
            return False
        return hasattr(self, "capture_result") and hasattr(self, "capture_start")

    def _capture_accepted(
        self, result: dict[str, Any], page_generation: int | None = None,
        request_generation: int | None = None, passphrase: str = "",
    ) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self._capture_failed(
                RuntimeError("El backend no devolvió operation_id."),
                page_generation, request_generation,
            )
            return
        self._local_operation_results = getattr(self, "_local_operation_results", {})
        self._local_operation_results[operation_id] = {"accepted": result, "status": None}
        request_is_latest = request_generation is None or request_generation == getattr(self, "_capture_request_generation", None)
        if request_is_latest:
            self.active_capture_id = operation_id
        if passphrase:
            self.api.submit(
                "provide_capture_passphrase",
                {"operation_id": operation_id, "passphrase": passphrase},
                on_success=lambda _response: self._capture_passphrase_delivered(
                    operation_id, page_generation
                ),
                on_error=lambda error: self._capture_passphrase_failed(
                    error, operation_id, page_generation
                ),
            )
        if request_is_latest and page_generation is not None and self._capture_view_is_current(page_generation):
            self.capture_passphrase.set_text("") if hasattr(self, "capture_passphrase") else None
            self.capture_cancel.set_sensitive(True)
            self.capture_result.set_text("Operación aceptada: " + operation_id)
            self.capture_progress.set_fraction(0.0)
            self._poll_capture_status(operation_id, page_generation)

    def _capture_passphrase_delivered(self, operation_id: str, page_generation: int | None) -> None:
        if page_generation is not None and self._capture_view_is_current(page_generation, operation_id):
            self.capture_result.set_text("Frase age entregada a la operación.")

    def _capture_passphrase_failed(
        self, error: Exception, operation_id: str | None = None,
        page_generation: int | None = None,
    ) -> None:
        self._capture_action_errors = getattr(self, "_capture_action_errors", {})
        if operation_id:
            self._capture_action_errors[operation_id] = str(error)
            self.api.submit(
                "cancel_local_operation",
                {"operation_id": operation_id},
                on_success=lambda _result: None,
                on_error=lambda cancel_error: self._capture_action_errors.__setitem__(
                    operation_id, str(cancel_error)
                ),
            )
        if page_generation is not None and operation_id and self._capture_view_is_current(page_generation, operation_id):
            self.capture_result.set_text("No se pudo entregar la frase age a la operación; se solicitó su cancelación: " + str(error))

    def _poll_capture_status(self, operation_id: str | None = None, page_generation: int | None = None) -> bool:
        operation_id = operation_id or getattr(self, "active_capture_id", None)
        page_generation = page_generation if page_generation is not None else getattr(self, "_capture_page_generation", None)
        if not operation_id:
            return GLib.SOURCE_REMOVE
        self.api.submit(
            "local_operation_status",
            {"operation_id": operation_id},
            on_success=lambda status: self._show_capture_status(status, operation_id, page_generation),
            on_error=lambda error: self._capture_status_failed(error, operation_id, page_generation),
        )
        return GLib.SOURCE_REMOVE

    def _show_capture_status(
        self, status: dict[str, Any], operation_id: str | None = None,
        page_generation: int | None = None,
    ) -> None:
        operation_id = operation_id or status.get("operation_id") or getattr(self, "active_capture_id", None)
        if not isinstance(operation_id, str) or not operation_id:
            return
        self._local_operation_results = getattr(self, "_local_operation_results", {})
        if status.get("operation_id") not in (None, operation_id):
            self._capture_action_errors = getattr(self, "_capture_action_errors", {})
            self._capture_action_errors[operation_id] = "El estado devuelto pertenece a otra operación."
            return
        self._local_operation_results.setdefault(operation_id, {})["status"] = status
        if page_generation is None or not self._capture_view_is_current(page_generation, operation_id):
            return
        events = status.get("events") or []
        event = next((e for e in reversed(events) if e.get("state") == "progress"), None)
        details = event.get("details", {}) if event else {}
        total, done = details.get("bytes_total"), details.get("bytes_done", 0)
        if isinstance(total, int) and total > 0 and isinstance(done, int):
            fraction = max(0.0, min(1.0, done / total))
            self.capture_progress.set_fraction(fraction)
            self.capture_progress.set_text(str(round(fraction * 100, 1)) + "%")
        state = status.get("state", "unknown")
        self.capture_result.set_text("Operación " + operation_id + ": " + str(state))
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            terminal = events[-1].get("details", {}) if events else {}
            detail = terminal.get("error") or terminal.get("reason") or terminal
            self.capture_result.set_text("Operación " + str(state) + ": " + str(detail))
            self.capture_start.set_sensitive(True)
            self.capture_cancel.set_sensitive(False)
            self.active_capture_id = None
            if state == "completed":
                self.api.submit(
                    "inventory",
                    on_success=lambda response: self._populate_capture_devices(response)
                    if self._capture_view_is_current(page_generation) else None,
                    on_error=lambda error: self._capture_failed(error, page_generation)
                    if self._capture_view_is_current(page_generation) else None,
                )
                self._capture_repository_changed(self.capture_repository, None)
            return
        GLib.timeout_add_seconds(2, lambda: self._poll_capture_status(operation_id, page_generation))

    def _capture_status_failed(
        self, error: Exception, operation_id: str | None = None,
        page_generation: int | None = None,
    ) -> None:
        if operation_id:
            self._capture_action_errors = getattr(self, "_capture_action_errors", {})
            self._capture_action_errors[operation_id] = "status: " + str(error)
        if operation_id and page_generation is not None and self._capture_view_is_current(page_generation, operation_id):
            self.capture_result.set_text("No se pudo consultar el progreso; la operación sigue identificada como activa: " + str(error))
            self.capture_cancel.set_sensitive(True)
            GLib.timeout_add_seconds(5, lambda: self._poll_capture_status(operation_id, page_generation))

    def _cancel_disk_capture(self, _button: Gtk.Button) -> None:
        operation_id = getattr(self, "active_capture_id", None)
        page_generation = self._capture_page_generation
        if not operation_id:
            return
        self.capture_cancel.set_sensitive(False)
        self.capture_result.set_text("Cancelación solicitada. La escritura podría dejar el destino parcialmente modificado.")
        self.api.submit(
            "cancel_local_operation",
            {"operation_id": operation_id},
            on_success=lambda _result: None,
            on_error=lambda error: self._capture_failed(error, page_generation, operation_id=operation_id),
        )

    def _capture_failed(
        self, error: Exception, page_generation: int | None = None,
        request_generation: int | None = None, operation_id: str | None = None,
    ) -> None:
        self._capture_action_errors = getattr(self, "_capture_action_errors", {})
        key = operation_id or (f"request:{request_generation}" if request_generation is not None else "latest")
        self._capture_action_errors[key] = str(error)
        if page_generation is None:
            page_generation = getattr(self, "_capture_page_generation", None)
        if page_generation is None or not self._capture_view_is_current(page_generation, operation_id):
            return
        if request_generation is not None and request_generation != getattr(self, "_capture_request_generation", None):
            return
        if hasattr(self, "capture_passphrase"):
            self.capture_passphrase.set_text("")
        self.capture_result.set_text("Operación fallida: " + str(error))
        self.capture_start.set_sensitive(True)
        self.capture_cancel.set_sensitive(False)

    def _refresh_status(self, _button: Gtk.Button | None) -> None:
        self._status_refresh_generation = getattr(self, "_status_refresh_generation", 0) + 1
        generation = self._status_refresh_generation
        page_generation = self._page_generation
        if hasattr(self, "status_summary"):
            self.status_summary.set_text("Consultando el estado del sistema…")
        if hasattr(self, "overview_configuration"):
            self.overview_configuration.set_text("Consultando configuración…")
        if hasattr(self, "overview_services"):
            self.overview_services.set_text("Consultando servicios…")
        self.api.submit(
            "status",
            on_success=lambda status: self._show_status(status, generation, page_generation),
            on_error=lambda error: self._show_error(error)
            if generation == self._status_refresh_generation and page_generation == self._page_generation else None,
        )

    def _show_status(
        self, status: dict[str, Any], generation: int | None = None, page_generation: int | None = None
    ) -> None:
        if generation is not None and generation != self._status_refresh_generation:
            return
        if page_generation is not None and page_generation != self._page_generation:
            return
        if not hasattr(self, "status_summary"):
            return
        self.status_summary.set_text(
            f"{status.get('hostname', '—')}\n{status.get('platform', '—')}"
        )
        if hasattr(self, "overview_configuration"):
            self.overview_configuration.set_text(
                f"Servidor: {'configurado' if status.get('server_configured') else 'no configurado'}\n"
                f"Cliente: {'configurado' if status.get('client_configured') else 'no configurado'}"
            )
        if hasattr(self, "overview_services"):
            services = status.get("services") or {}
            self.overview_services.set_text(
                "\n".join(f"{name}: {state}" for name, state in services.items())
                or "La API no ha comunicado servicios."
            )
        if hasattr(self, "system_details_group"):
            while child := self.system_details_group.get_first_child():
                self.system_details_group.remove(child)
            components = [
                ("Servidor configurado", "Sí" if status.get("server_configured") else "No"),
                ("Cliente configurado", "Sí" if status.get("client_configured") else "No"),
            ]
            components.extend(
                (f"Servicio {name}", str(state or "—"))
                for name, state in (status.get("services") or {}).items()
            )
            components.extend(
                (f"Certificado {item.get('role', '')}", str(item.get("status") or "—"))
                for item in status.get("certificate_status") or []
                if isinstance(item, dict)
            )
            if not components:
                self.system_details_group.add(Adw.ActionRow(
                    title="Sin detalles adicionales",
                    subtitle="La API no ha comunicado servicios ni certificados.",
                ))
            for name, value in components:
                row = Adw.ActionRow(title=name, subtitle=value)
                self.system_details_group.add(row)

    @staticmethod
    def _flatten_devices(devices: Any) -> list[dict[str, Any]]:
        if not isinstance(devices, list):
            return []
        flattened: list[dict[str, Any]] = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            flattened.append(device)
            flattened.extend(FecloraGTK._flatten_devices(device.get("children")))
        return flattened

    def _refresh_inventory(self, _button: Gtk.Button | None) -> None:
        self._inventory_refresh_generation = getattr(self, "_inventory_refresh_generation", 0) + 1
        generation = self._inventory_refresh_generation
        page_generation = self._page_generation
        self.inventory_summary.set_text("Leyendo inventario de almacenamiento…")
        self.api.submit(
            "inventory",
            on_success=lambda response: self._show_inventory(response, generation, page_generation),
            on_error=lambda error: self._show_error(error)
            if generation == self._inventory_refresh_generation and page_generation == self._page_generation else None,
        )

    @staticmethod
    def _inventory_device_subtitle(device: dict[str, Any]) -> str:
        size = device.get("size_bytes")
        mountpoints = device.get("mountpoints") or []
        values = (
            f"Tipo: {device.get('type') or '—'}",
            f"Tamaño: {size if size is not None else '—'} bytes",
            f"Modelo: {device.get('model') or '—'}",
            f"Sistema de archivos: {device.get('filesystem') or '—'}",
            f"Montajes: {', '.join(str(point) for point in mountpoints) if mountpoints else '—'}",
        )
        return " · ".join(values)

    def _append_inventory_device(
        self, group: Adw.PreferencesGroup, device: dict[str, Any], depth: int = 0
    ) -> int:
        path = str(device.get("path") or "Dispositivo sin ruta")
        title = f"{'↳ ' if depth else ''}{path}"
        row = Adw.ActionRow(
            title=title,
            subtitle=self._inventory_device_subtitle(device),
        )
        group.add(row)
        count = 1
        children = device.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    count += self._append_inventory_device(group, child, depth + 1)
        return count

    def _show_inventory(
        self, inventory: dict[str, Any], generation: int | None = None, page_generation: int | None = None
    ) -> None:
        if generation is not None and generation != self._inventory_refresh_generation:
            return
        if page_generation is not None and page_generation != self._page_generation:
            return
        if not hasattr(self, "inventory_content"):
            return
        while child := self.inventory_content.get_first_child():
            self.inventory_content.remove(child)
        roots = inventory.get("devices")
        if not isinstance(roots, list):
            roots = []
        devices = [device for device in roots if isinstance(device, dict)]
        if not devices:
            self.inventory_content.append(Adw.StatusPage(
                title="No se detectaron dispositivos",
                description="La API de inventario no ha comunicado dispositivos de almacenamiento.",
                icon_name="drive-harddisk-symbolic",
            ))
            self.inventory_summary.set_text("Dispositivos detectados: 0")
            return

        count = 0
        for device in devices:
            path = str(device.get("path") or "Dispositivo sin ruta")
            group = Adw.PreferencesGroup(
                title=path,
                description="Dispositivo y componentes subordinados detectados.",
            )
            self.inventory_content.append(group)
            count += self._append_inventory_device(group, device)
        self.inventory_summary.set_text(f"Dispositivos detectados: {count}")

    def _select_placeholder(self, _button: Gtk.Button, page_id: str) -> None:
        self._select_page(_button, page_id)


def main() -> None:
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("Feclora GTK requires a native Wayland session (WAYLAND_DISPLAY missing)")
    app = Adw.Application(application_id="org.feclora.Appliance")
    frontend: FecloraGTK | None = None

    def activate(application: Adw.Application) -> None:
        nonlocal frontend
        if frontend is None:
            frontend = FecloraGTK(application)

    app.connect("activate", activate)

    def shutdown(_application: Gtk.Application) -> None:
        if frontend is not None:
            frontend.api.close()

    app.connect("shutdown", shutdown)
    app.run(None)


if __name__ == "__main__":
    main()
