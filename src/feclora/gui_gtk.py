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
        elif page_id == "images":
            self._show_images_page()
        elif page_id == "operations":
            self.page_description.set_text("Captura, restauración y clonación local. Las escrituras destructivas exigen confirmar exactamente el destino.")
            self.capture_summary = Gtk.Label(label="Consultando inventario…", xalign=0)
            self.page_body.append(self.capture_summary)
            self.capture_kind = Gtk.DropDown.new_from_strings(["Capturar disco completo", "Capturar partición", "Capturar volumen lógico", "Capturar filesystem Stratis", "Capturar subvolumen Btrfs", "Recibir stream Btrfs", "Recuperar disco con ddrescue", "Finalizar recuperación ddrescue", "Restaurar disco", "Restaurar partición", "Restaurar volumen lógico", "Clonar disco", "Clonar partición", "Restaurar filesystem Stratis", "Construir ISO de recuperación", "Construir bundle de despliegue", "Restauración proporcional a disco menor"])
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
        self.image_repository.connect("notify::selected", self._image_repository_changed)
        self.image_select.connect("notify::selected", self._image_selection_changed)
        self.image_partition.connect("notify::selected", self._image_partition_changed)
        self.api.submit("remote_repositories", on_success=self._populate_image_repositories, on_error=self._image_page_failed)

    def _populate_image_repositories(self, result: dict[str, Any]) -> None:
        self.image_repositories = [item for item in result.get("repositories", []) if isinstance(item, dict)]
        labels = [str(item.get("id")) + (" · solo lectura" if item.get("read_only") else "") for item in self.image_repositories]
        self.image_repository.set_model(Gtk.StringList.new(labels or ["Repositorio local"]))
        self.image_repository.set_selected(0)
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
        self.image_listing.set_text("\\n".join(
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
            with destination.open("xb") as stream:
                stream.write(data)
            destination.chmod(0o600)
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
        if kind in {0, 6, 11, 16}:
            self.capture_devices = [d for d in self.capture_inventory_devices if d.get("type") == "disk" and isinstance(d.get("path"), str)]
            label = "Discos" if kind == 0 else "Discos para recuperación ddrescue" if kind == 6 else "Discos de origen para restauración proporcional" if kind == 16 else "Discos de origen para clonación"
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
        self.capture_compression.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15})
        self.capture_encrypt.set_visible(kind not in {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15})
        self.capture_image_id_label.set_text("Identificador del stream Btrfs" if kind in {4, 5} else "ID del trabajo de recuperación" if kind == 7 else "ID de recuperación" if kind == 6 else "Identificador de imagen")
        self.capture_start.set_label("Recibir stream Btrfs" if kind == 5 else "Iniciar recuperación ddrescue" if kind == 6 else "Finalizar recuperación ddrescue" if kind == 7 else "Restaurar proporcionalmente" if is_proportional else "Iniciar restauración" if is_restore else "Iniciar clonación" if is_clone else "Construir ISO de recuperación" if is_recovery_iso else "Construir bundle de despliegue" if is_bundle else "Iniciar captura: " + label.lower())

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
