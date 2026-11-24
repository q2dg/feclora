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
        content.append(self.page_body)

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
        elif page_id == "operations":
            self.page_description.set_text("Captura, restauración y clonación local. Las escrituras destructivas exigen confirmar exactamente el destino.")
            self.capture_summary = Gtk.Label(label="Consultando inventario…", xalign=0)
            self.page_body.append(self.capture_summary)
            self.capture_kind = Gtk.DropDown.new_from_strings(["Capturar disco completo", "Capturar partición", "Capturar volumen lógico", "Capturar filesystem Stratis", "Capturar subvolumen Btrfs", "Recibir stream Btrfs", "Recuperar disco con ddrescue", "Finalizar recuperación ddrescue", "Restaurar disco", "Restaurar partición", "Restaurar volumen lógico", "Clonar disco", "Clonar partición"])
            self.capture_kind.connect("notify::selected", self._capture_mode_changed)
            self.page_body.append(self.capture_kind)
            self.page_body.append(Gtk.Label(label="Origen", xalign=0))
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
            self.capture_confirmation.set_placeholder_text("ERASE /dev/…")
            self.page_body.append(self.capture_confirmation)
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
            self.api.submit("images", on_success=self._populate_capture_images, on_error=self._capture_failed)
        else:
            self.page_description.set_text("Esta pantalla aún no se ha migrado. Sus operaciones permanecen disponibles en la interfaz de producción.")

    def _populate_capture_devices(self, inventory: dict[str, Any]) -> None:
        self.capture_inventory = inventory
        self.capture_inventory_devices = self._flatten_devices(inventory.get("devices"))
        self._capture_mode_changed(self.capture_kind, None)

    def _populate_capture_images(self, result: dict[str, Any]) -> None:
        self.capture_images = [item for item in result.get("images", []) if isinstance(item, dict) and item.get("image_id")]
        labels = [str(item.get("image_id")) + " · " + str(item.get("image_type")) + " · " + str(item.get("source_size_bytes", 0)) + " bytes" for item in self.capture_images]
        self.capture_image_select.set_model(Gtk.StringList.new(labels or ["No hay imágenes disponibles"]))
        self.capture_image_select.set_selected(0)

    def _capture_mode_changed(self, _dropdown: Gtk.DropDown, _pspec: Any) -> None:
        kind = self.capture_kind.get_selected()
        is_btrfs_capture = kind == 4
        is_btrfs_receive = kind == 5
        is_recovery = kind == 6
        is_finalize = kind == 7
        is_restore = kind in {8, 9, 10}
        is_clone = kind in {11, 12}
        self.capture_source.set_visible(not (is_btrfs_capture or is_btrfs_receive or is_finalize or is_restore))
        self.capture_target_label.set_visible(is_restore or is_clone)
        self.capture_target.set_visible(is_restore or is_clone)
        self.capture_image_select_label.set_visible(is_restore)
        self.capture_image_select.set_visible(is_restore)
        self.capture_confirmation_label.set_visible(is_restore or is_clone)
        self.capture_confirmation.set_visible(is_restore or is_clone)
        self.capture_btrfs_source.set_visible(is_btrfs_capture)
        self.capture_btrfs_parent.set_visible(is_btrfs_capture)
        self.capture_btrfs_target.set_visible(is_btrfs_receive)
        self.capture_btrfs_receive_parent.set_visible(is_btrfs_receive)
        self.capture_retry.set_visible(is_recovery)
        self.capture_resume.set_visible(is_recovery)
        if kind in {0, 6, 11}:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "disk" and isinstance(d.get("path"), str)]
            label = "Discos" if kind == 0 else "Discos para recuperación ddrescue"
        elif kind in {1, 12}:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "part" and isinstance(d.get("path"), str)]
            label = "Particiones"
        elif kind in {2, 10}:
            self.capture_devices = self._flatten_logical_volumes(self.capture_inventory)
            label = "Volúmenes lógicos sanos"
        elif kind == 3:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "dm" and str(d.get("filesystem") or "").lower() == "xfs" and isinstance(d.get("path"), str)]
            label = "Filesystems Stratis XFS"
        elif kind in {4, 5}:
            self.capture_devices = []
            label = "Subvolúmenes Btrfs (ruta manual)"
        elif kind in {8, 9}:
            device_type = "disk" if kind == 8 else "part"
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == device_type and isinstance(d.get("path"), str)]
            label = "Destinos de restauración · " + ("discos" if kind == 8 else "particiones")
        else:
            self.capture_devices = []
            label = "Finalización de recuperación"
        labels = [str(d.get("path")) + " · " + str(d.get("model") or d.get("lvm_name") or d.get("type")) for d in self.capture_devices]
        self.capture_source.set_model(Gtk.StringList.new(labels or ["No hay dispositivos compatibles"]))
        self.capture_source.set_selected(0)
        target_type = "disk" if kind in {8, 11} else "part"
        self.capture_target_devices = self._flatten_logical_volumes(self.capture_inventory) if kind == 10 else [d for d in self.capture_inventory_devices if d.get("type") == target_type and isinstance(d.get("path"), str)]
        target_labels = [str(d.get("path")) + " · " + str(d.get("model") or d.get("type")) for d in self.capture_target_devices]
        self.capture_target.set_model(Gtk.StringList.new(target_labels or ["No hay destinos compatibles"]))
        self.capture_target.set_selected(0)
        self.capture_summary.set_text(label + " detectados: " + str(len(self.capture_devices)))
        self.capture_format_label.set_visible(kind == 0)
        self.capture_format.set_visible(kind == 0)
        self.capture_compression.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12})
        self.capture_encrypt.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12})
        self.capture_image_id_label.set_text("Identificador del stream Btrfs" if kind in {4, 5} else "ID del trabajo de recuperación" if kind == 7 else "ID de recuperación" if kind == 6 else "Identificador de imagen")
        self.capture_start.set_label("Recibir stream Btrfs" if kind == 5 else "Iniciar recuperación ddrescue" if kind == 6 else "Finalizar recuperación ddrescue" if kind == 7 else "Iniciar restauración" if is_restore else "Iniciar clonación" if is_clone else "Iniciar captura: " + label.lower())

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
        if kind in {8, 9, 10, 11, 12}:
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
                expected_type = {8: "disk", 9: "partition", 10: "logical_volume"}[kind]
                if image.get("image_type") != expected_type:
                    self.capture_result.set_text("La imagen seleccionada no corresponde al tipo de restauración.")
                    return
                expected = "ERASE " + target
                action = {8: "restore_disk", 9: "restore_partition", 10: "restore_logical_volume"}[kind]
                params = {"image_id": image["image_id"], "target": target, "confirmation": confirmation}
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
        self.status_summary.set_text("\\n".join(lines))

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
