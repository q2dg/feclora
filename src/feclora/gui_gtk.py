"""GTK4 frontend prototype for the native Wayland Feclora kiosk.

This frontend is not the production boot entry point until every operator
workflow has been migrated and accepted. The existing Textual service remains
enabled during the staged migration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Fail closed: do not allow GDK to select X11/XWayland as a fallback.
os.environ["GDK_BACKEND"] = "wayland"
os.environ.pop("DISPLAY", None)

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from feclora.gtk_api import GtkAPIClient
from feclora.ui_catalog import KEYBOARD_LAYOUTS, LANGUAGES, MESSAGES, PAGES, PAGE_MESSAGE_KEYS


class FecloraGTK:
    def __init__(self, application: Gtk.Application) -> None:
        self.application = application
        self.language = self._load_language()
        self.keyboard_layout = "us"
        self.api = GtkAPIClient()
        self.window = Gtk.ApplicationWindow(application=application)
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

    def _accept_keyboard_layout(self, result: dict[str, Any]) -> None:
        layout = result.get("layout")
        values = [value for _label, value in KEYBOARD_LAYOUTS]
        if layout in values:
            self.keyboard_layout = layout
            if hasattr(self, "keyboard_dropdown"):
                self.keyboard_dropdown.set_selected(values.index(layout))

    @staticmethod
    def _box(orientation: Gtk.Orientation, spacing: int = 12) -> Gtk.Box:
        return Gtk.Box(orientation=orientation, spacing=spacing)

    def _show_welcome(self) -> None:
        root = self._box(Gtk.Orientation.VERTICAL, 18)
        root.set_halign(Gtk.Align.CENTER)
        root.set_valign(Gtk.Align.CENTER)
        root.set_margin_top(48)
        root.set_margin_bottom(48)
        root.set_margin_start(64)
        root.set_margin_end(64)

        title = Gtk.Label(label=self.tr("first_title"))
        title.add_css_class("title-1")
        root.append(title)
        tagline = Gtk.Label(label=self.tr("tagline"))
        tagline.set_wrap(True)
        root.append(tagline)

        root.append(Gtk.Label(label=self.tr("language")))
        self.language_dropdown = Gtk.DropDown.new_from_strings([label for label, _code in LANGUAGES])
        self.language_dropdown.set_selected(next((i for i, (_label, code) in enumerate(LANGUAGES) if code == self.language), 1))
        self.language_dropdown.connect("notify::selected", self._language_changed)
        root.append(self.language_dropdown)

        root.append(Gtk.Label(label=self.tr("keyboard")))
        self.keyboard_dropdown = Gtk.DropDown.new_from_strings([label for label, _value in KEYBOARD_LAYOUTS])
        root.append(self.keyboard_dropdown)

        self.status = Gtk.Label(label=self.tr("language_scope"))
        self.status.set_wrap(True)
        root.append(self.status)

        apply_button = Gtk.Button(label=self.tr("apply_keyboard"))
        apply_button.connect("clicked", self._apply_keyboard)
        root.append(apply_button)
        continue_button = Gtk.Button(label=self.tr("continue"))
        continue_button.connect("clicked", self._continue)
        root.append(continue_button)
        terminal_button = Gtk.Button(label=self.tr("terminal"))
        terminal_button.connect("clicked", self._open_root_terminal)
        root.append(terminal_button)

        self.window.set_child(root)
        self.window.present()

    def _language_changed(self, dropdown: Gtk.DropDown, _param: Any) -> None:
        index = dropdown.get_selected()
        if index < len(LANGUAGES):
            self.language = LANGUAGES[index][1]
            self._show_welcome()

    def _apply_keyboard(self, _button: Gtk.Button) -> None:
        index = self.keyboard_dropdown.get_selected()
        layout = KEYBOARD_LAYOUTS[index][1] if index < len(KEYBOARD_LAYOUTS) else "us"
        self.status.set_text("Aplicando distribución del teclado…")
        self.api.submit(
            "set_keyboard_layout", {"layout": layout},
            on_success=lambda _result: self.status.set_text(self.tr("apply_ok")),
            on_error=self._show_error,
        )

    def _open_root_terminal(self, _button: Gtk.Button) -> None:
        self.api.submit(
            "open_root_terminal",
            on_success=lambda _result: self.status.set_text("Solicitud de terminal root enviada."),
            on_error=self._show_error,
        )

    def _continue(self, _button: Gtk.Button) -> None:
        try:
            self._save_language(self.language)
        except OSError as exc:
            self.status.set_text(f"No se pudo guardar el idioma: {exc}")
            return
        self._show_navigation()

    def _show_navigation(self) -> None:
        outer = self._box(Gtk.Orientation.HORIZONTAL, 0)
        sidebar = self._box(Gtk.Orientation.VERTICAL, 8)
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

        for page_id, _label in PAGES:
            button = Gtk.Button(label=self.tr(PAGE_MESSAGE_KEYS[page_id]))
            button.set_halign(Gtk.Align.FILL)
            button.connect("clicked", self._select_page, page_id)
            sidebar.append(button)

        outer.append(sidebar)
        outer.append(content)
        self.window.set_child(outer)
        self._select_page(None, "overview")

    def _clear_page(self) -> None:
        child = self.page_body.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.page_body.remove(child)
            child = following

    def _select_page(self, _button: Gtk.Button | None, page_id: str) -> None:
        self._clear_page()
        self.page_title.set_text(self.tr(PAGE_MESSAGE_KEYS[page_id]))
        if page_id == "overview":
            self.page_description.set_text("Estado del equipo y configuración local.")
            self.status_summary = Gtk.Label(label="Consultando el estado del sistema…", xalign=0)
            self.status_summary.set_selectable(True)
            self.page_body.append(self.status_summary)
            refresh = Gtk.Button(label="Actualizar estado")
            refresh.set_halign(Gtk.Align.START)
            refresh.connect("clicked", self._refresh_status)
            self.page_body.append(refresh)
            self._refresh_status(None)
        elif page_id == "inventory":
            self.page_description.set_text("Inventario de dispositivos de almacenamiento detectados.")
            self.inventory_summary = Gtk.Label(label="Leyendo inventario…", xalign=0)
            self.page_body.append(self.inventory_summary)
            refresh = Gtk.Button(label="Actualizar inventario")
            refresh.set_halign(Gtk.Align.START)
            refresh.connect("clicked", self._refresh_inventory)
            self.page_body.append(refresh)
            scroller = Gtk.ScrolledWindow()
            scroller.set_vexpand(True)
            self.inventory_grid = Gtk.Grid(column_spacing=16, row_spacing=8)
            scroller.set_child(self.inventory_grid)
            self.page_body.append(scroller)
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
            self.page_description.set_text("Captura, restauración y clonación local. Las escrituras destructivas exigen confirmar exactamente el destino.")
            self.capture_summary = Gtk.Label(label="Consultando inventario…", xalign=0)
            self.page_body.append(self.capture_summary)
            self.capture_kind = Gtk.DropDown.new_from_strings(["Capturar disco completo", "Capturar partición", "Capturar volumen lógico", "Capturar filesystem Stratis", "Capturar subvolumen Btrfs", "Recibir stream Btrfs", "Recuperar disco con ddrescue", "Finalizar recuperación ddrescue", "Restaurar disco", "Restaurar partición", "Restaurar volumen lógico", "Clonar disco", "Clonar partición", "Restaurar filesystem Stratis", "Construir ISO de recuperación", "Construir bundle de despliegue", "Restauración proporcional a disco menor", "Capturar disco virtual QCOW2 (P2V)"])
            self.capture_kind.connect("notify::selected", self._capture_mode_changed)
            self.page_body.append(self.capture_kind)
            self.capture_source_label = Gtk.Label(label="Origen", xalign=0)
            self.page_body.append(self.capture_source_label)
            self.capture_source = Gtk.DropDown.new_from_strings(["Cargando dispositivos…"])
            self.page_body.append(self.capture_source)
            self.capture_target_label = Gtk.Label(label="Destino", xalign=0)
            self.page_body.append(self.capture_target_label)
            self.capture_target = Gtk.DropDown.new_from_strings(["Cargando dispositivos…"])
            self.page_body.append(self.capture_target)
            self.capture_image_select_label = Gtk.Label(label="Imagen existente", xalign=0)
            self.page_body.append(self.capture_image_select_label)
            self.capture_image_select = Gtk.DropDown.new_from_strings(["Cargando imágenes…"])
            self.page_body.append(self.capture_image_select)
            self.capture_confirmation_label = Gtk.Label(label="Confirmación destructiva", xalign=0)
            self.page_body.append(self.capture_confirmation_label)
            self.capture_confirmation = Gtk.Entry()
            self.capture_confirmation.set_placeholder_text("ERASE /dev/… o BUILD <imagen>")
            self.page_body.append(self.capture_confirmation)
            self.capture_repository_label = Gtk.Label(label="Repositorio remoto", xalign=0)
            self.page_body.append(self.capture_repository_label)
            self.capture_repository = Gtk.DropDown.new_from_strings(["Cargando repositorios…"])
            self.page_body.append(self.capture_repository)
            self.capture_base_iso_label = Gtk.Label(label="Ruta absoluta de la ISO base", xalign=0)
            self.page_body.append(self.capture_base_iso_label)
            self.capture_base_iso = Gtk.Entry()
            self.capture_base_iso.set_placeholder_text("/ruta/absoluta/feclora-live.iso")
            self.page_body.append(self.capture_base_iso)
            self.capture_target_wwn = Gtk.Entry()
            self.capture_target_wwn.set_placeholder_text("WWN destino (opcional)")
            self.page_body.append(self.capture_target_wwn)
            self.capture_target_serial = Gtk.Entry()
            self.capture_target_serial.set_placeholder_text("Número de serie destino (opcional)")
            self.page_body.append(self.capture_target_serial)
            self.capture_bundle_name_label = Gtk.Label(label="Nombre del bundle", xalign=0)
            self.page_body.append(self.capture_bundle_name_label)
            self.capture_bundle_name = Gtk.Entry()
            self.capture_bundle_name.set_text("fleet-deployment-bundle")
            self.page_body.append(self.capture_bundle_name)
            self.capture_deployment_job_label = Gtk.Label(label="DeploymentJob (JSON)", xalign=0)
            self.page_body.append(self.capture_deployment_job_label)
            self.capture_deployment_job = Gtk.TextView()
            self.capture_deployment_job.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.capture_deployment_job.set_size_request(-1, 140)
            self.page_body.append(self.capture_deployment_job)
            self.capture_btrfs_source = Gtk.Entry()
            self.capture_btrfs_source.set_placeholder_text("/ruta/al/subvolumen")
            self.page_body.append(Gtk.Label(label="Ruta absoluta del subvolumen Btrfs", xalign=0))
            self.page_body.append(self.capture_btrfs_source)
            self.capture_btrfs_parent = Gtk.Entry()
            self.capture_btrfs_parent.set_placeholder_text("Opcional: ruta del subvolumen padre")
            self.page_body.append(Gtk.Label(label="Padre incremental (opcional)", xalign=0))
            self.page_body.append(self.capture_btrfs_parent)
            self.capture_btrfs_target = Gtk.Entry()
            self.capture_btrfs_target.set_placeholder_text("/directorio/destino/montado")
            self.page_body.append(Gtk.Label(label="Directorio destino Btrfs ya montado", xalign=0))
            self.page_body.append(self.capture_btrfs_target)
            self.capture_btrfs_receive_parent = Gtk.Entry()
            self.capture_btrfs_receive_parent.set_placeholder_text("Opcional: ruta del subvolumen padre recibido")
            self.page_body.append(Gtk.Label(label="Padre recibido (opcional)", xalign=0))
            self.page_body.append(self.capture_btrfs_receive_parent)
            self.capture_image_id_label = Gtk.Label(label="Identificador de imagen", xalign=0)
            self.page_body.append(self.capture_image_id_label)
            self.capture_image_id = Gtk.Entry()
            self.capture_image_id.set_placeholder_text("Identificador de imagen")
            self.page_body.append(self.capture_image_id)
            self.capture_format_label = Gtk.Label(label="Formato de imagen", xalign=0)
            self.page_body.append(self.capture_format_label)
            self.capture_format = Gtk.DropDown.new_from_strings(["RAW de Feclora", "QCOW2"])
            self.page_body.append(self.capture_format)
            self.capture_compression = Gtk.DropDown.new_from_strings(["Zstandard", "LZ4", "Gzip", "XZ", "Sin compresión"])
            self.page_body.append(self.capture_compression)
            self.capture_encrypt = Gtk.CheckButton(label="Cifrar artefactos con age")
            self.page_body.append(self.capture_encrypt)
            self.capture_retry = Gtk.DropDown.new_from_strings([str(n) for n in range(11)])
            self.capture_retry.set_selected(3)
            self.page_body.append(Gtk.Label(label="Pasadas de reintento ddrescue", xalign=0))
            self.page_body.append(self.capture_retry)
            self.capture_resume = Gtk.CheckButton(label="Reanudar recuperación existente (mapfile)")
            self.page_body.append(self.capture_resume)
            self.capture_start = Gtk.Button(label="Iniciar captura de disco")
            self.capture_start.connect("clicked", self._start_disk_capture)
            self.page_body.append(self.capture_start)
            self.capture_cancel = Gtk.Button(label="Solicitar cancelación")
            self.capture_cancel.set_sensitive(False)
            self.capture_cancel.connect("clicked", self._cancel_disk_capture)
            self.page_body.append(self.capture_cancel)
            self.capture_progress = Gtk.ProgressBar()
            self.capture_progress.set_show_text(True)
            self.page_body.append(self.capture_progress)
            self.capture_result = Gtk.Label(label="", xalign=0)
            self.capture_result.set_wrap(True)
            self.page_body.append(self.capture_result)
            self.api.submit("inventory", on_success=self._populate_capture_devices, on_error=self._capture_failed)
            self.api.submit("remote_repositories", on_success=self._populate_capture_repositories, on_error=self._capture_failed)
        else:
            self.page_description.set_text("Esta pantalla aún no se ha migrado. Sus operaciones permanecen disponibles en la interfaz de producción.")

    def _history_page(self, title: str, columns: tuple[str, ...], action: str, key: str, renderer: Any) -> None:
        self.page_description.set_text(title)
        self.history_summary = Gtk.Label(label="Consultando registros…", xalign=0)
        self.page_body.append(self.history_summary)
        refresh = Gtk.Button(label="Actualizar")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", lambda _button: self._refresh_history(action, key, renderer))
        self.page_body.append(refresh)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.history_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.history_grid)
        self.page_body.append(scroller)
        self.history_columns = columns
        self._refresh_history(action, key, renderer)

    def _refresh_history(self, action: str, key: str, renderer: Any) -> None:
        self.history_summary.set_text("Consultando " + action + "…")
        self.api.submit(action, on_success=lambda response: self._show_history_rows(response, key, renderer), on_error=self._history_failed)

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
        self.status_summary = Gtk.Label(label="Consultando estado del sistema…", xalign=0)
        self.status_summary.set_wrap(True)
        self.status_summary.set_selectable(True)
        self.page_body.append(self.status_summary)
        refresh = Gtk.Button(label="Actualizar estado del sistema")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", self._refresh_status)
        self.page_body.append(refresh)
        self._refresh_status(None)

    def _show_server_status_page(self) -> None:
        self.page_description.set_text("Estado del servidor Feclora, servicios PXE e interfaces. Los controles de bootstrap, certificados y PXE siguen pendientes de migración.")
        self.server_status = Gtk.Label(label="Consultando estado del servidor…", xalign=0)
        self.server_status.set_wrap(True)
        self.server_status.set_selectable(True)
        self.page_body.append(self.server_status)
        refresh = Gtk.Button(label="Actualizar estado del servidor")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", self._refresh_server_status)
        self.page_body.append(refresh)
        self._refresh_server_status(None)

    def _refresh_server_status(self, _button: Gtk.Button | None) -> None:
        self.server_status_parts: dict[str, Any] = {}
        self.server_status.set_text("Consultando estado, PXE e interfaces…")
        self.api.submit("status", on_success=lambda value: self._server_status_part("status", value), on_error=self._server_status_failed)
        self.api.submit("pxe_service_status", on_success=lambda value: self._server_status_part("pxe", value), on_error=self._server_status_failed)
        self.api.submit("network_interfaces", on_success=lambda value: self._server_status_part("interfaces", value), on_error=self._server_status_failed)

    def _server_status_part(self, key: str, value: dict[str, Any]) -> None:
        self.server_status_parts[key] = value
        if set(self.server_status_parts) != {"status", "pxe", "interfaces"}:
            return
        status = self.server_status_parts["status"]
        pxe = self.server_status_parts["pxe"]
        interfaces = self.server_status_parts["interfaces"].get("interfaces") or []
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

    def _server_status_failed(self, error: Exception) -> None:
        self.server_status.set_text("No se pudo consultar el estado del servidor: " + str(error))

    def _show_repositories_page(self) -> None:
        self.page_description.set_text("Estado de los repositorios de archivos remotos y S3 disponibles para las operaciones.")
        self.repositories_summary = Gtk.Label(label="Consultando repositorios…", xalign=0)
        self.page_body.append(self.repositories_summary)
        refresh = Gtk.Button(label="Actualizar repositorios")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", self._refresh_repositories)
        self.page_body.append(refresh)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.repositories_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.repositories_grid)
        self.page_body.append(scroller)

        p2v_title = Gtk.Label(label="Compatibilidad P2V heredada", xalign=0)
        p2v_title.add_css_class("heading")
        self.page_body.append(p2v_title)
        self.page_body.append(Gtk.Label(label="Importa bundles QCOW2 heredados desde un repositorio de archivos; exporta bundles heredados desde S3.", xalign=0))
        self.p2v_import_repository = Gtk.DropDown.new_from_strings(["Repositorio local"])
        self.page_body.append(Gtk.Label(label="Repositorio de origen para importar", xalign=0))
        self.page_body.append(self.p2v_import_repository)
        self.p2v_source_image_id = Gtk.Entry()
        self.p2v_source_image_id.set_placeholder_text("Identificador QCOW2 heredado")
        self.page_body.append(self.p2v_source_image_id)
        self.p2v_import_image_id = Gtk.Entry()
        self.p2v_import_image_id.set_placeholder_text("Nuevo identificador de imagen Feclora")
        self.page_body.append(self.p2v_import_image_id)
        p2v_import = Gtk.Button(label="Importar bundle P2V heredado")
        p2v_import.set_halign(Gtk.Align.START)
        p2v_import.connect("clicked", self._import_legacy_p2v)
        self.page_body.append(p2v_import)

        self.p2v_export_repository = Gtk.DropDown.new_from_strings(["Selecciona repositorio S3…"])
        self.page_body.append(Gtk.Label(label="Repositorio S3 de origen para exportar", xalign=0))
        self.page_body.append(self.p2v_export_repository)
        self.p2v_export_image_id = Gtk.Entry()
        self.p2v_export_image_id.set_placeholder_text("Identificador QCOW2 heredado")
        self.page_body.append(self.p2v_export_image_id)
        self.p2v_export_destination = Gtk.DropDown.new_from_strings(["Repositorio local"])
        self.page_body.append(Gtk.Label(label="Destino (opcional; vacío = repositorio local)", xalign=0))
        self.page_body.append(self.p2v_export_destination)
        p2v_export = Gtk.Button(label="Exportar bundle P2V desde S3")
        p2v_export.set_halign(Gtk.Align.START)
        p2v_export.connect("clicked", self._export_legacy_p2v)
        self.page_body.append(p2v_export)
        self.p2v_result = Gtk.Label(label="", xalign=0)
        self.p2v_result.set_wrap(True)
        self.p2v_result.set_selectable(True)
        self.page_body.append(self.p2v_result)

        self._refresh_repositories(None)

    def _refresh_repositories(self, _button: Gtk.Button | None) -> None:
        self.repositories_summary.set_text("Consultando repositorios de archivos y S3…")
        self.api.submit("remote_repositories", on_success=self._populate_remote_repositories, on_error=self._repositories_failed)
        self.api.submit("s3_repositories", on_success=self._populate_s3_repositories, on_error=self._repositories_failed)

    def _populate_remote_repositories(self, response: dict[str, Any]) -> None:
        self.remote_repository_rows = [("NFS/SSH", item) for item in response.get("repositories", []) if isinstance(item, dict)]
        if hasattr(self, "p2v_import_repository"):
            usable = [item for item in self.remote_repository_rows if item[1].get("mounted") and item[1].get("verified") and not item[1].get("read_only")]
            self.p2v_import_repositories = usable
            labels = ["Repositorio local"] + [str(item.get("id")) for _, item in usable]
            self.p2v_import_repository.set_model(Gtk.StringList.new(labels))
            self.p2v_export_destinations = usable
            self.p2v_export_destination.set_model(Gtk.StringList.new(["Repositorio local"] + [str(item.get("id")) for _, item in usable]))
        self._render_repositories()

    def _populate_s3_repositories(self, response: dict[str, Any]) -> None:
        self.s3_repository_rows = [("S3", item) for item in response.get("repositories", []) if isinstance(item, dict)]
        if hasattr(self, "p2v_export_repository"):
            usable = [item for _, item in self.s3_repository_rows]
            self.p2v_export_repositories = usable
            labels = ["Selecciona repositorio S3…"] + [str(item.get("id")) for item in usable]
            self.p2v_export_repository.set_model(Gtk.StringList.new(labels))
            self.p2v_export_repository.set_selected(0)
        self._render_repositories()

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
        self.api.submit("import_p2v", params, on_success=self._p2v_operation_accepted, on_error=self._p2v_operation_failed)

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
        self.api.submit("export_p2v_s3", params, on_success=self._p2v_operation_accepted, on_error=self._p2v_operation_failed)

    def _p2v_operation_accepted(self, result: dict[str, Any]) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self._p2v_operation_failed(RuntimeError("El backend no devolvió operation_id."))
            return
        self.p2v_result.set_text("Operación P2V aceptada: " + operation_id + ". Consulta Operation Log para ver progreso, resultado y errores.")

    def _p2v_operation_failed(self, error: Exception) -> None:
        self.p2v_result.set_text("No se pudo iniciar la operación P2V: " + str(error))

    def _render_repositories(self) -> None:
        if not hasattr(self, "repositories_grid"):
            return
        rows = getattr(self, "remote_repository_rows", []) + getattr(self, "s3_repository_rows", [])
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
        self.page_description.set_text("Estado de los clientes asociados a los trabajos de despliegue.")
        self.history_summary = Gtk.Label(label="Consultando clientes…", xalign=0)
        self.page_body.append(self.history_summary)
        refresh = Gtk.Button(label="Actualizar clientes")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", lambda _button: self.api.submit("deployment_jobs", on_success=self._show_client_job_rows, on_error=self._history_failed))
        self.page_body.append(refresh)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.history_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.history_grid)
        self.page_body.append(scroller)
        self._show_client_job_rows({"jobs": []})
        self.api.submit("deployment_jobs", on_success=self._show_client_job_rows, on_error=self._history_failed)

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
        self.page_description.set_text("Historial persistente de operaciones locales, incluidos errores y estados terminales.")
        self.operation_log_summary = Gtk.Label(label="Consultando operaciones…", xalign=0)
        self.page_body.append(self.operation_log_summary)
        refresh = Gtk.Button(label="Actualizar registro")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", self._refresh_operation_log)
        self.page_body.append(refresh)
        self.operation_select = Gtk.DropDown.new_from_strings(["Selecciona operación…"])
        self.page_body.append(self.operation_select)
        self.operation_confirmation = Gtk.Entry()
        self.operation_confirmation.set_placeholder_text("CANCEL <operation_id>")
        self.page_body.append(self.operation_confirmation)
        cancel = Gtk.Button(label="Solicitar cancelación (confirmación exacta)")
        cancel.set_halign(Gtk.Align.START)
        cancel.connect("clicked", self._cancel_selected_logged_operation)
        self.page_body.append(cancel)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.operation_log_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.operation_log_grid)
        self.page_body.append(scroller)
        self._refresh_operation_log(None)

    def _refresh_operation_log(self, _button: Gtk.Button | None) -> None:
        self.operation_log_summary.set_text("Leyendo el registro duradero…")
        self.api.submit("local_operations", on_success=self._show_operation_log, on_error=self._operation_log_failed)

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
        self.operation_log_summary.set_text(f"Operaciones registradas: {len(operations)} · errores de inspección: {len(errors)}" + (" · ATENCIÓN: existen registros que requieren inspección manual; no repitas esas operaciones." if errors else ""))

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
        self.api.submit("cancel_local_operation", {"operation_id": operation_id}, on_success=self._operation_cancelled, on_error=self._operation_log_failed)

    def _operation_cancelled(self, result: dict[str, Any]) -> None:
        self.operation_confirmation.set_text("")
        self.operation_log_summary.set_text("Resultado de cancelación: " + str(result))
        self._refresh_operation_log(None)

    def _operation_log_failed(self, error: Exception) -> None:
        self.operation_log_summary.set_text("No se pudo leer el registro de operaciones: " + str(error))

    def _show_recovery_jobs_page(self) -> None:
        self.page_description.set_text("Trabajos ddrescue persistentes. Los mapfiles permiten reanudar recuperaciones interrumpidas.")
        self.recovery_jobs_summary = Gtk.Label(label="Consultando trabajos…", xalign=0)
        self.page_body.append(self.recovery_jobs_summary)
        refresh = Gtk.Button(label="Actualizar recuperaciones")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", self._refresh_recovery_jobs)
        self.page_body.append(refresh)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.recovery_jobs_grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        scroller.set_child(self.recovery_jobs_grid)
        self.page_body.append(scroller)
        self._refresh_recovery_jobs(None)

    def _refresh_recovery_jobs(self, _button: Gtk.Button | None) -> None:
        self.recovery_jobs_summary.set_text("Leyendo trabajos ddrescue…")
        self.api.submit("recovery_jobs", on_success=self._show_recovery_jobs, on_error=self._recovery_jobs_failed)

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
        self.recovery_jobs_summary.set_text(f"Trabajos de recuperación: {len(jobs)} · los trabajos interrumpidos conservan su mapfile para reanudación")

    def _recovery_jobs_failed(self, error: Exception) -> None:
        self.recovery_jobs_summary.set_text("No se pudieron consultar los trabajos ddrescue: " + str(error))

    def _show_network_page(self) -> None:
        self.page_description.set_text("Configuración IPv4 de perfiles activos de NetworkManager, con aplicación protegida por checkpoint y rollback.")
        self.network_profile = Gtk.DropDown.new_from_strings(["Cargando perfiles…"])
        self.network_profile.connect("notify::selected", self._network_profile_changed)
        self.page_body.append(Gtk.Label(label="Perfil activo de NetworkManager", xalign=0))
        self.page_body.append(self.network_profile)
        self.network_interface = Gtk.DropDown.new_from_strings(["Selecciona interfaz y dirección…"])
        self.page_body.append(Gtk.Label(label="Dirección IPv4 actualmente asociada", xalign=0))
        self.page_body.append(self.network_interface)
        self.network_method = Gtk.DropDown.new_from_strings(["Automática (DHCP)", "Manual (IPv4 estática)"])
        self.network_method.connect("notify::selected", self._network_method_changed)
        self.page_body.append(Gtk.Label(label="Método IPv4", xalign=0))
        self.page_body.append(self.network_method)
        self.network_address = Gtk.Entry()
        self.network_address.set_placeholder_text("192.0.2.10")
        self.page_body.append(Gtk.Label(label="Dirección IPv4", xalign=0))
        self.page_body.append(self.network_address)
        self.network_prefix = Gtk.Entry()
        self.network_prefix.set_placeholder_text("24")
        self.page_body.append(Gtk.Label(label="Prefijo CIDR (1–32)", xalign=0))
        self.page_body.append(self.network_prefix)
        self.network_gateway = Gtk.Entry()
        self.network_gateway.set_placeholder_text("192.0.2.1 (opcional)")
        self.page_body.append(Gtk.Label(label="Gateway IPv4 (opcional)", xalign=0))
        self.page_body.append(self.network_gateway)
        self.network_dns = Gtk.Entry()
        self.network_dns.set_placeholder_text("1.1.1.1, 8.8.8.8")
        self.page_body.append(Gtk.Label(label="DNS IPv4 separados por comas", xalign=0))
        self.page_body.append(self.network_dns)
        apply = Gtk.Button(label="Aplicar configuración (rollback automático si falla)")
        apply.set_halign(Gtk.Align.START)
        apply.connect("clicked", self._apply_network_profile)
        self.page_body.append(apply)
        self.network_result = Gtk.Label(label="", xalign=0)
        self.network_result.set_wrap(True)
        self.page_body.append(self.network_result)
        self._network_method_changed(self.network_method, None)
        self.api.submit("network_connection_profiles", on_success=self._populate_network_profiles, on_error=self._network_failed)
        self.api.submit("network_interfaces", on_success=self._populate_network_interfaces, on_error=self._network_failed)

    def _populate_network_profiles(self, result: dict[str, Any]) -> None:
        self.network_profiles = [item for item in result.get("profiles", []) if isinstance(item, dict)]
        active = [item for item in self.network_profiles if item.get("uuid") and item.get("active") and item.get("device")]
        labels = [f"{item.get('name') or item.get('id')} · {item.get('device')}" for item in active]
        self.network_active_profiles = active
        self.network_profile.set_model(Gtk.StringList.new(labels or ["No hay perfiles activos asociados a interfaces"]))
        self.network_profile.set_selected(0)
        self._update_network_interface_options()

    def _populate_network_interfaces(self, result: dict[str, Any]) -> None:
        self.network_interfaces = [item for item in result.get("interfaces", []) if isinstance(item, dict)]
        self._update_network_interface_options()

    def _network_profile_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._update_network_interface_options()

    def _update_network_interface_options(self) -> None:
        index = self.network_profile.get_selected()
        profile = self.network_active_profiles[index] if index < len(getattr(self, "network_active_profiles", [])) else None
        interface_name = profile.get("device") if profile else None
        candidates = [item for item in getattr(self, "network_interfaces", []) if item.get("binding") and item.get("interface") == interface_name]
        labels = [f"{item.get('interface')} · {item.get('address')}/{item.get('prefix_length')}" for item in candidates]
        self.network_interface_records = candidates
        self.network_interface.set_model(Gtk.StringList.new(labels or ["No hay direcciones IPv4 activas en esa interfaz"]))
        self.network_interface.set_selected(0)

    def _network_method_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        manual = self.network_method.get_selected() == 1
        for widget in (self.network_address, self.network_prefix, self.network_gateway, self.network_dns):
            widget.set_visible(manual)

    def _apply_network_profile(self, _button: Gtk.Button) -> None:
        import ipaddress
        profile_index = self.network_profile.get_selected()
        interface_index = self.network_interface.get_selected()
        if profile_index >= len(getattr(self, "network_active_profiles", [])) or interface_index >= len(getattr(self, "network_interface_records", [])):
            self.network_result.set_text("Selecciona un perfil activo y una dirección IPv4 de su interfaz.")
            return
        profile = self.network_active_profiles[profile_index]
        interface = self.network_interface_records[interface_index]
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
        self.network_result.set_text("Aplicando perfil con checkpoint de 120 segundos…")
        self.api.submit("apply_network_profile", params, on_success=self._network_applied, on_error=self._network_failed)

    def _network_applied(self, result: dict[str, Any]) -> None:
        self.network_result.set_text(str(result.get("message") or "Perfil aplicado y verificado; checkpoint confirmado."))
        self.api.submit("network_connection_profiles", on_success=self._populate_network_profiles, on_error=self._network_failed)
        self.api.submit("network_interfaces", on_success=self._populate_network_interfaces, on_error=self._network_failed)

    def _network_failed(self, error: Exception) -> None:
        if hasattr(self, "network_result"):
            self.network_result.set_text("No se pudo completar la operación de red: " + str(error))

    def _show_restore_profiles_page(self) -> None:
        self.page_description.set_text("Perfiles de restauración de un solo uso, vinculados a la identidad física del disco y con caducidad.")
        self.profile_repository = Gtk.DropDown.new_from_strings(["Cargando repositorios…"])
        self.page_body.append(Gtk.Label(label="Repositorio persistente (montado, verificado y escribible)", xalign=0))
        self.page_body.append(self.profile_repository)
        self.profile_image = Gtk.DropDown.new_from_strings(["Selecciona imagen RAW de disco…"])
        self.page_body.append(Gtk.Label(label="Imagen RAW de disco", xalign=0))
        self.page_body.append(self.profile_image)
        self.profile_target = Gtk.DropDown.new_from_strings(["Cargando discos…"])
        self.page_body.append(Gtk.Label(label="Disco destino con WWN o número de serie", xalign=0))
        self.page_body.append(self.profile_target)
        self.profile_name = Gtk.Entry()
        self.profile_name.set_placeholder_text("Nombre descriptivo del perfil")
        self.page_body.append(Gtk.Label(label="Nombre del perfil", xalign=0))
        self.page_body.append(self.profile_name)
        self.profile_expiry = Gtk.Entry()
        self.profile_expiry.set_placeholder_text("2027-01-31T23:59:59+01:00")
        self.page_body.append(Gtk.Label(label="Caducidad ISO-8601 con zona horaria", xalign=0))
        self.page_body.append(self.profile_expiry)
        create = Gtk.Button(label="Crear perfil (no ejecuta la restauración)")
        create.set_halign(Gtk.Align.START)
        create.connect("clicked", self._create_restore_profile)
        self.page_body.append(create)
        self.profile_select = Gtk.DropDown.new_from_strings(["Cargando perfiles…"])
        self.page_body.append(Gtk.Label(label="Perfil guardado", xalign=0))
        self.page_body.append(self.profile_select)
        self.profile_confirmation = Gtk.Entry()
        self.profile_confirmation.set_placeholder_text("ERASE /dev/…")
        self.page_body.append(Gtk.Label(label="Confirmación exacta del disco detectado", xalign=0))
        self.page_body.append(self.profile_confirmation)
        execute = Gtk.Button(label="Ejecutar perfil de restauración")
        execute.set_halign(Gtk.Align.START)
        execute.connect("clicked", self._execute_selected_restore_profile)
        self.page_body.append(execute)
        self.profile_cancel = Gtk.Button(label="Solicitar cancelación de restauración")
        self.profile_cancel.set_sensitive(False)
        self.profile_cancel.connect("clicked", self._cancel_restore_profile_operation)
        self.page_body.append(self.profile_cancel)
        self.profile_result = Gtk.Label(label="", xalign=0)
        self.profile_result.set_wrap(True)
        self.profile_result.set_selectable(True)
        self.page_body.append(self.profile_result)
        self.api.submit("inventory", on_success=self._populate_profile_inventory, on_error=self._profile_failed)
        self.api.submit("remote_repositories", on_success=self._populate_profile_repositories, on_error=self._profile_failed)

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
        repository = self._selected_profile_repository()
        self.profile_images = []
        self.profile_records = []
        if not repository:
            self.profile_image.set_model(Gtk.StringList.new(["Selecciona un repositorio válido"]))
            self.profile_select.set_model(Gtk.StringList.new(["No hay perfiles disponibles"]))
            return
        repository_id = repository["id"]
        self.api.submit("repository_images", {"repository_id": repository_id}, on_success=self._populate_profile_images, on_error=self._profile_failed)
        self.api.submit("restore_profiles", {"repository_id": repository_id}, on_success=self._populate_restore_profiles, on_error=self._profile_failed)

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
        self.api.submit("create_restore_profile", params, on_success=self._restore_profile_created, on_error=self._profile_failed)

    def _restore_profile_created(self, result: dict[str, Any]) -> None:
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
        self.api.submit("execute_restore_profile", params, on_success=self._restore_profile_operation_accepted, on_error=self._profile_failed)

    def _restore_profile_operation_accepted(self, result: dict[str, Any]) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self._profile_failed(RuntimeError("El backend no devolvió operation_id."))
            return
        self.profile_operation_id = operation_id
        self.profile_cancel.set_sensitive(True)
        self.profile_result.set_text("Restauración aceptada por el worker duradero: " + operation_id)
        GLib.timeout_add_seconds(1, self._poll_restore_profile_operation)

    def _poll_restore_profile_operation(self) -> bool:
        operation_id = getattr(self, "profile_operation_id", None)
        if not operation_id:
            return GLib.SOURCE_REMOVE
        self.api.submit("local_operation_status", {"operation_id": operation_id}, on_success=self._show_restore_profile_operation_status, on_error=self._profile_operation_status_failed)
        return GLib.SOURCE_REMOVE

    def _show_restore_profile_operation_status(self, status: dict[str, Any]) -> None:
        state = status.get("state", "unknown")
        events = status.get("events") or []
        self.profile_result.set_text("Restauración " + str(self.profile_operation_id) + ": " + str(state))
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            terminal = events[-1].get("details", {}) if events else {}
            self.profile_result.set_text("Restauración " + str(state) + ": " + str(terminal.get("error") or terminal.get("reason") or terminal))
            self.profile_cancel.set_sensitive(False)
            self.profile_operation_id = None
            self.profile_confirmation.set_text("")
            self._load_restore_profiles_for_repository()
        else:
            GLib.timeout_add_seconds(2, self._poll_restore_profile_operation)

    def _profile_operation_status_failed(self, error: Exception) -> None:
        self.profile_result.set_text("No se pudo consultar el estado; conserva el ID del trabajo: " + str(error))
        GLib.timeout_add_seconds(5, self._poll_restore_profile_operation)

    def _cancel_restore_profile_operation(self, _button: Gtk.Button) -> None:
        operation_id = getattr(self, "profile_operation_id", None)
        if operation_id:
            self.profile_cancel.set_sensitive(False)
            self.api.submit("cancel_local_operation", {"operation_id": operation_id}, on_success=lambda _result: None, on_error=self._profile_failed)

    def _profile_failed(self, error: Exception) -> None:
        if hasattr(self, "profile_result"):
            self.profile_result.set_text("Operación de perfil fallida: " + str(error))

    def _show_images_page(self) -> None:
        self.page_description.set_text("Inspección verificada de imágenes de disco, exploración de archivos y extracción de particiones.")
        self.image_repository = Gtk.DropDown.new_from_strings(["Cargando repositorios…"])
        self.image_repository_label = Gtk.Label(label="Repositorio", xalign=0)
        self.page_body.append(self.image_repository_label)
        self.page_body.append(self.image_repository)
        self.image_select = Gtk.DropDown.new_from_strings(["Cargando imágenes de disco…"])
        self.page_body.append(Gtk.Label(label="Imagen de disco", xalign=0))
        self.page_body.append(self.image_select)
        inspect = Gtk.Button(label="Inspeccionar tabla de particiones")
        inspect.set_halign(Gtk.Align.START)
        inspect.connect("clicked", self._inspect_selected_image)
        self.page_body.append(inspect)
        self.image_partition = Gtk.DropDown.new_from_strings(["Inspecciona primero la imagen…"])
        self.page_body.append(Gtk.Label(label="Partición", xalign=0))
        self.page_body.append(self.image_partition)
        self.image_browse_path = Gtk.Entry()
        self.image_browse_path.set_text("/")
        self.page_body.append(Gtk.Label(label="Ruta dentro del filesystem", xalign=0))
        self.page_body.append(self.image_browse_path)
        browse = Gtk.Button(label="Explorar directorio")
        browse.set_halign(Gtk.Align.START)
        browse.connect("clicked", self._browse_selected_image)
        self.page_body.append(browse)
        self.image_download_path = Gtk.Entry()
        self.image_download_path.set_placeholder_text("/ruta/al/archivo")
        self.page_body.append(Gtk.Label(label="Archivo a descargar (ruta absoluta)", xalign=0))
        self.page_body.append(self.image_download_path)
        download = Gtk.Button(label="Descargar archivo en ~/Downloads")
        download.set_halign(Gtk.Align.START)
        download.connect("clicked", self._download_selected_image_file)
        self.page_body.append(download)
        extract = Gtk.Button(label="Extraer partición como imagen")
        extract.set_halign(Gtk.Align.START)
        extract.connect("clicked", self._extract_selected_partition)
        self.page_body.append(extract)
        self.image_cancel = Gtk.Button(label="Cancelar extracción")
        self.image_cancel.set_sensitive(False)
        self.image_cancel.connect("clicked", self._cancel_image_extraction)
        self.page_body.append(self.image_cancel)
        verify = Gtk.Button(label="Verificar integridad completa de la imagen")
        verify.set_halign(Gtk.Align.START)
        verify.connect("clicked", self._verify_selected_image)
        self.page_body.append(verify)
        self.image_result = Gtk.Label(label="", xalign=0)
        self.image_result.set_wrap(True)
        self.image_result.set_selectable(True)
        self.page_body.append(self.image_result)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.image_listing = Gtk.Label(label="", xalign=0, yalign=0)
        self.image_listing.set_selectable(True)
        self.image_listing.set_wrap(True)
        scroller.set_child(self.image_listing)
        self.page_body.append(scroller)
        self.image_select.connect("notify::selected", self._image_selection_changed)
        self.image_partition.connect("notify::selected", self._image_partition_changed)
        self.api.submit("remote_repositories", on_success=self._populate_image_repositories, on_error=self._image_page_failed)

    def _populate_image_repositories(self, result: dict[str, Any]) -> None:
        self.image_repositories = [item for item in result.get("repositories", []) if isinstance(item, dict)]
        labels = [str(item.get("id")) + (" · solo lectura" if item.get("read_only") else "") for item in self.image_repositories]
        self.image_repository.set_model(Gtk.StringList.new(labels or ["Repositorio local"]))
        self.image_repository.set_selected(0)
        self.image_repository.connect("notify::selected", self._image_repository_changed)
        self._load_image_catalog()

    def _image_repository_id(self) -> str | None:
        index = self.image_repository.get_selected()
        if index < len(getattr(self, "image_repositories", [])):
            return self.image_repositories[index].get("id")
        return None

    def _image_repository_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._load_image_catalog()

    def _load_image_catalog(self) -> None:
        repository_id = self._image_repository_id()
        if repository_id:
            self.api.submit("repository_images", {"repository_id": repository_id}, on_success=self._populate_image_catalog, on_error=self._image_page_failed)
        else:
            self.api.submit("images", on_success=self._populate_image_catalog, on_error=self._image_page_failed)

    def _populate_image_catalog(self, result: dict[str, Any]) -> None:
        self.image_catalog = [item for item in result.get("images", []) if isinstance(item, dict) and item.get("image_type") == "disk" and item.get("image_id")]
        labels = [str(item["image_id"]) + " · " + str(item.get("source_size_bytes", 0)) + " bytes" for item in self.image_catalog]
        self.image_select.set_model(Gtk.StringList.new(labels or ["No hay imágenes de disco"]))
        self.image_select.set_selected(0)
        self._reset_image_layout()

    def _image_selection_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        self._reset_image_layout()

    def _reset_image_layout(self) -> None:
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
        self.api.submit("verify_image", params, on_success=self._show_image_verification, on_error=self._image_page_failed)

    def _show_image_verification(self, result: dict[str, Any]) -> None:
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
        self.image_result.set_text("Verificando manifiesto y tabla de particiones…")
        self.api.submit("inspect_image_layout", params, on_success=self._show_image_layout, on_error=self._image_page_failed)

    def _show_image_layout(self, layout: dict[str, Any]) -> None:
        image = self._selected_image()
        if not image or layout.get("image_id") != image["image_id"]:
            self._reset_image_layout()
            self.image_result.set_text("La respuesta corresponde a otra imagen; vuelve a inspeccionar.")
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
        self.api.submit("browse_image", params, on_success=self._show_image_directory, on_error=self._image_page_failed)

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
        self.api.submit("browse_image", params, on_success=self._save_image_download, on_error=self._image_page_failed)

    def _save_image_download(self, result: dict[str, Any]) -> None:
        import base64
        filename, encoded = result.get("filename"), result.get("content_base64")
        if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(encoded, str):
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
            self.image_result.set_text(f"No se pudo guardar el archivo: {exc}")
            return
        self.image_result.set_text(f"Archivo guardado: {destination}")

    def _image_partition_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
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
        if repository and (repository.get("read_only") or not repository.get("mounted") or not repository.get("verified")):
            self.image_result.set_text("La extracción requiere un repositorio montado, verificado y escribible.")
            return
        params = {"image_id": image["image_id"], "selector": selector}
        if repository_id:
            params["repository_id"] = repository_id
        self.image_result.set_text("Solicitando extracción de partición…")
        self.api.submit("extract_partition_image", params, on_success=self._image_extraction_accepted, on_error=self._image_page_failed)

    def _image_extraction_accepted(self, result: dict[str, Any]) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self.image_result.set_text("El backend no devolvió operation_id.")
            return
        self.image_operation_id = operation_id
        self.image_cancel.set_sensitive(True)
        self.image_result.set_text("Extracción aceptada: " + operation_id)
        GLib.timeout_add_seconds(1, self._poll_image_extraction)

    def _poll_image_extraction(self) -> bool:
        operation_id = getattr(self, "image_operation_id", None)
        if not operation_id:
            return GLib.SOURCE_REMOVE
        self.api.submit("local_operation_status", {"operation_id": operation_id}, on_success=self._show_image_extraction_status, on_error=self._image_extraction_status_failed)
        return GLib.SOURCE_REMOVE

    def _show_image_extraction_status(self, status: dict[str, Any]) -> None:
        events = status.get("events") or []
        event = next((item for item in reversed(events) if item.get("state") == "progress"), None)
        details = event.get("details", {}) if event else {}
        total, done = details.get("bytes_total"), details.get("bytes_done", 0)
        progress = f" · {round(done / total * 100, 1)}%" if isinstance(total, int) and total > 0 and isinstance(done, int) else ""
        state = status.get("state", "unknown")
        self.image_result.set_text(f"Extracción {self.image_operation_id}: {state}{progress}")
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            terminal = events[-1].get("details", {}) if events else {}
            self.image_result.set_text(f"Extracción {state}: {terminal.get('error') or terminal.get('reason') or terminal}")
            self.image_cancel.set_sensitive(False)
            self.image_operation_id = None
        else:
            GLib.timeout_add_seconds(2, self._poll_image_extraction)

    def _image_extraction_status_failed(self, error: Exception) -> None:
        self.image_result.set_text("No se pudo consultar el progreso; el trabajo conserva su ID: " + str(error))
        GLib.timeout_add_seconds(5, self._poll_image_extraction)

    def _cancel_image_extraction(self, _button: Gtk.Button) -> None:
        operation_id = getattr(self, "image_operation_id", None)
        if operation_id:
            self.image_cancel.set_sensitive(False)
            self.api.submit("cancel_local_operation", {"operation_id": operation_id}, on_success=lambda _result: None, on_error=self._image_page_failed)

    def _image_page_failed(self, error: Exception) -> None:
        if hasattr(self, "image_result"):
            self.image_result.set_text("Operación de imagen fallida: " + str(error))

    def _populate_capture_devices(self, inventory: dict[str, Any]) -> None:
        self.capture_inventory = inventory
        self.capture_inventory_devices = self._flatten_devices(inventory.get("devices"))
        self._capture_mode_changed(self.capture_kind, None)

    def _populate_capture_images(self, result: dict[str, Any]) -> None:
        self.capture_images = [item for item in result.get("images", []) if isinstance(item, dict) and item.get("image_id")]
        labels = [str(item.get("image_id")) + " · " + str(item.get("image_type")) + " · " + str(item.get("source_size_bytes", 0)) + " bytes" for item in self.capture_images]
        self.capture_image_select.set_model(Gtk.StringList.new(labels or ["No hay imágenes disponibles"]))
        self.capture_image_select.set_selected(0)

    def _populate_capture_repositories(self, result: dict[str, Any]) -> None:
        self.capture_repositories = [item for item in result.get("repositories", []) if isinstance(item, dict)]
        labels = [str(item.get("id")) + (" · disponible" if item.get("mounted") and item.get("verified") and not item.get("read_only") else " · no disponible para escritura") for item in self.capture_repositories]
        self.capture_repository.set_model(Gtk.StringList.new(labels or ["Repositorio local"]))
        usable = next((i for i, item in enumerate(self.capture_repositories) if item.get("mounted") and item.get("verified")), None)
        self.capture_repository.set_selected(usable if usable is not None else 0)
        self.capture_repository.connect("notify::selected", self._capture_repository_changed)
        self._capture_repository_changed(self.capture_repository, None)

    def _capture_repository_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        index = self.capture_repository.get_selected()
        if index < len(getattr(self, "capture_repositories", [])):
            repository = self.capture_repositories[index]
            if repository.get("mounted") and repository.get("verified"):
                self.api.submit("repository_images", {"repository_id": repository["id"]}, on_success=self._populate_capture_images, on_error=self._capture_failed)
                return
        self.api.submit("images", on_success=self._populate_capture_images, on_error=self._capture_failed)

    def _capture_mode_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        kind = self.capture_kind.get_selected()
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
        self.capture_image_id_label.set_visible(not (is_restore or is_clone or is_image_build))
        self.capture_image_id.set_visible(not (is_restore or is_clone or is_image_build))
        for widget in (self.capture_repository_label, self.capture_repository):
            widget.set_visible(is_restore or is_image_build)
        for widget in (self.capture_base_iso_label, self.capture_base_iso):
            widget.set_visible(is_image_build)
        for widget in (self.capture_target_wwn, self.capture_target_serial):
            widget.set_visible(is_recovery_iso)
        self.capture_bundle_name_label.set_visible(is_bundle)
        self.capture_bundle_name.set_visible(is_bundle)
        self.capture_deployment_job_label.set_visible(is_bundle)
        self.capture_deployment_job.set_visible(is_bundle)
        self.capture_image_select_label.set_visible(is_restore or is_image_build)
        self.capture_image_select.set_visible(is_restore or is_image_build)
        self.capture_btrfs_source.set_visible(is_btrfs_capture)
        self.capture_btrfs_parent.set_visible(is_btrfs_capture)
        self.capture_btrfs_target.set_visible(is_btrfs_receive)
        self.capture_btrfs_receive_parent.set_visible(is_btrfs_receive)
        self.capture_retry.set_visible(is_recovery)
        self.capture_resume.set_visible(is_recovery)
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
        self.capture_format.set_visible(kind == 0)
        self.capture_compression.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17})
        self.capture_encrypt.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17})
        self.capture_image_id_label.set_text("Identificador del stream Btrfs" if kind in {4, 5} else "ID del trabajo de recuperación" if kind == 7 else "ID de recuperación" if kind == 6 else "Identificador de imagen")
        self.capture_start.set_label("Recibir stream Btrfs" if kind == 5 else "Iniciar recuperación ddrescue" if kind == 6 else "Finalizar recuperación ddrescue" if kind == 7 else "Restaurar proporcionalmente" if is_proportional else "Capturar disco virtual QCOW2 (P2V)" if kind == 17 else "Iniciar restauración" if is_restore else "Iniciar clonación" if is_clone else "Construir ISO de recuperación" if is_recovery_iso else "Construir bundle de despliegue" if is_bundle else "Iniciar captura: " + label.lower())

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
            if image_index >= len(getattr(self, "capture_images", [])) or repository_index >= len(getattr(self, "capture_repositories", [])):
                self.capture_result.set_text("Selecciona una imagen y un repositorio válidos.")
                return
            image = self.capture_images[image_index]
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
            self.api.submit(action, params, on_success=self._capture_accepted, on_error=self._capture_failed)
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
                if image_index >= len(getattr(self, "capture_images", [])):
                    self.capture_result.set_text("Selecciona una imagen compatible.")
                    return
                image = self.capture_images[image_index]
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
                    if selected_repository.get("mounted") and selected_repository.get("verified"):
                        params["repository_id"] = selected_repository["id"]
            if confirmation != expected:
                self.capture_result.set_text("Escribe exactamente: " + expected)
                return
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando operación destructiva…")
            self.api.submit(action, params, on_success=self._capture_accepted, on_error=self._capture_failed)
            return
        if kind == 7:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Indica un identificador válido del trabajo de recuperación.")
                return
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando finalización de recuperación…")
            self.api.submit("finalize_recovery", {"job_id": image_id}, on_success=self._capture_accepted, on_error=self._capture_failed)
            return
        if kind == 6:
            if index >= len(getattr(self, "capture_devices", [])) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Selecciona un disco completo e indica un ID de recuperación válido.")
                return
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id, "retry_passes": self.capture_retry.get_selected(), "resume": self.capture_resume.get_active()}
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando recuperación ddrescue…")
            self.api.submit("recover_disk", params, on_success=self._capture_accepted, on_error=self._capture_failed)
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
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando recepción Btrfs…")
            self.api.submit("receive_btrfs_subvolume", params, on_success=self._capture_accepted, on_error=self._capture_failed)
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
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando captura Btrfs…")
            self.api.submit("capture_btrfs_subvolume", params, on_success=self._capture_accepted, on_error=self._capture_failed)
            return
        if kind == 17:
            if index >= len(getattr(self, "capture_devices", [])) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", image_id):
                self.capture_result.set_text("Selecciona un disco de origen e indica un identificador de imagen válido.")
                return
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id}
            repository_index = self.capture_repository.get_selected()
            if repository_index < len(getattr(self, "capture_repositories", [])):
                repository = self.capture_repositories[repository_index]
                if repository.get("mounted") and repository.get("verified") and not repository.get("read_only"):
                    params["repository_id"] = repository["id"]
            self.capture_start.set_sensitive(False)
            self.capture_result.set_text("Solicitando captura P2V…")
            self.api.submit("capture_p2v", params, on_success=self._capture_accepted, on_error=self._capture_failed)
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
            params = {"source": self.capture_devices[index]["path"], "image_id": image_id, "image_format": "qcow2" if qcow2 else "raw", "compression": "none" if qcow2 else compression, "encrypt": self.capture_encrypt.get_active() and not qcow2}
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
        self.capture_start.set_sensitive(False)
        self.capture_result.set_text("Solicitando captura…")
        self.api.submit(action, params, on_success=self._capture_accepted, on_error=self._capture_failed)

    def _capture_accepted(self, result: dict[str, Any]) -> None:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            self._capture_failed(RuntimeError("El backend no devolvió operation_id."))
            return
        self.active_capture_id = operation_id
        self.capture_cancel.set_sensitive(True)
        self.capture_result.set_text("Captura aceptada: " + operation_id)
        self._poll_capture_status()

    def _poll_capture_status(self) -> bool:
        operation_id = getattr(self, "active_capture_id", None)
        if not operation_id:
            return GLib.SOURCE_REMOVE
        self.api.submit("local_operation_status", {"operation_id": operation_id}, on_success=self._show_capture_status, on_error=self._capture_status_failed)
        return GLib.SOURCE_REMOVE

    def _show_capture_status(self, status: dict[str, Any]) -> None:
        events = status.get("events") or []
        event = next((e for e in reversed(events) if e.get("state") == "progress"), None)
        details = event.get("details", {}) if event else {}
        total, done = details.get("bytes_total"), details.get("bytes_done", 0)
        if isinstance(total, int) and total > 0 and isinstance(done, int):
            fraction = max(0.0, min(1.0, done / total))
            self.capture_progress.set_fraction(fraction)
            self.capture_progress.set_text(str(round(fraction * 100, 1)) + "%")
        state = status.get("state", "unknown")
        self.capture_result.set_text("Operación " + str(self.active_capture_id) + ": " + str(state))
        if state in {"completed", "failed", "cancelled", "interrupted"}:
            terminal = events[-1].get("details", {}) if events else {}
            detail = terminal.get("error") or terminal.get("reason") or terminal
            self.capture_result.set_text("Operación " + str(state) + ": " + str(detail))
            self.capture_start.set_sensitive(True)
            self.capture_cancel.set_sensitive(False)
            self.active_capture_id = None
            return
        GLib.timeout_add_seconds(2, self._poll_capture_status)

    def _capture_status_failed(self, error: Exception) -> None:
        self.capture_result.set_text("No se pudo consultar el progreso; la operación sigue identificada como activa: " + str(error))
        self.capture_cancel.set_sensitive(True)
        GLib.timeout_add_seconds(5, self._poll_capture_status)

    def _cancel_disk_capture(self, _button: Gtk.Button) -> None:
        operation_id = getattr(self, "active_capture_id", None)
        if not operation_id:
            return
        self.capture_cancel.set_sensitive(False)
        self.capture_result.set_text("Cancelación solicitada. La escritura podría dejar el destino parcialmente modificado.")
        self.api.submit("cancel_local_operation", {"operation_id": operation_id}, on_success=lambda _result: None, on_error=self._capture_failed)

    def _capture_failed(self, error: Exception) -> None:
        if hasattr(self, "capture_result"):
            self.capture_result.set_text("Captura fallida: " + str(error))
            self.capture_start.set_sensitive(True)

    def _refresh_status(self, _button: Gtk.Button | None) -> None:
        self.status_summary.set_text("Consultando el estado local…")
        self.api.submit("status", on_success=self._show_status, on_error=self._show_error)

    def _show_status(self, status: dict[str, Any]) -> None:
        if not hasattr(self, "status_summary"):
            return
        lines = [
            f"Equipo: {status.get('hostname', '—')}",
            f"Sistema: {status.get('platform', '—')}",
            f"Servidor configurado: {'sí' if status.get('server_configured') else 'no'}",
            f"Cliente configurado: {'sí' if status.get('client_configured') else 'no'}",
        ]
        lines.extend(f"Servicio {name}: {state}" for name, state in (status.get("services") or {}).items())
        self.status_summary.set_text("\n".join(lines))

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
        self.inventory_summary.set_text("Leyendo inventario de almacenamiento…")
        self.api.submit("inventory", on_success=self._show_inventory, on_error=self._show_error)

    def _show_inventory(self, inventory: dict[str, Any]) -> None:
        if not hasattr(self, "inventory_grid"):
            return
        grid = self.inventory_grid
        while child := grid.get_first_child():
            grid.remove(child)
        headers = ("Dispositivo", "Tipo", "Tamaño (bytes)", "Modelo", "Sistema de archivos", "Montajes")
        for column, heading in enumerate(headers):
            label = Gtk.Label(label=heading, xalign=0)
            label.add_css_class("heading")
            grid.attach(label, column, 0, 1, 1)
        devices = self._flatten_devices(inventory.get("devices"))
        for row, device in enumerate(devices, start=1):
            values = (
                device.get("path") or "—", device.get("type") or "—",
                str(device.get("size_bytes") or "—"), device.get("model") or "—",
                device.get("filesystem") or "—", ", ".join(device.get("mountpoints") or []) or "—",
            )
            for column, value in enumerate(values):
                label = Gtk.Label(label=str(value), xalign=0)
                label.set_selectable(True)
                grid.attach(label, column, row, 1, 1)
        self.inventory_summary.set_text(f"Dispositivos detectados: {len(devices)}")

    def _select_placeholder(self, _button: Gtk.Button, page_id: str) -> None:
        self._select_page(_button, page_id)


def main() -> None:
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("Feclora GTK requires a native Wayland session (WAYLAND_DISPLAY missing)")
    app = Gtk.Application(application_id="org.feclora.Appliance")
    frontend: FecloraGTK | None = None

    def activate(application: Gtk.Application) -> None:
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
