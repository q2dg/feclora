"""Keyboard-first Textual interface for the Feclora Live appliance."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Input, ProgressBar, Select, Static

from feclora.tui_api import TUIAPIError, call_feclora

PAGES = (
    ("overview", "Inicio"),
    ("operations", "Operaciones"),
    ("restore-profiles", "Perfiles de restauración"),
    ("inventory", "Inventario"),
    ("images", "Imágenes"),
    ("remote-jobs", "Tareas remotas"),
    ("deployments", "Historial de despliegues"),
    ("repositories", "Repositorios"),
    ("operation-log", "Registro de operaciones"),
    ("network", "Red"),
    ("server", "Configuración del servidor"),
    ("client-jobs", "Tareas del cliente"),
    ("system", "Sistema"),
)

OPERATIONS = (
    ("Capturar disco", "capture_disk"),
    ("Capturar partición", "capture_partition"),
    ("Capturar volumen lógico", "capture_logical_volume"),
    ("Restaurar disco", "restore_disk"),
    ("Restaurar proporcionalmente a un disco menor", "restore_proportional_disk"),
    ("Restaurar partición", "restore_partition"),
    ("Restaurar volumen lógico", "restore_logical_volume"),
    ("Clonar disco", "clone_disk"),
    ("Clonar partición", "clone_partition"),
)
COMPRESSION = (("Zstandard", "zstd"), ("LZ4", "lz4"), ("Gzip", "gzip"), ("XZ", "xz"), ("Sin compresión", "none"))
LANGUAGES = (
    ("English", "en"), ("Español", "es"), ("Català", "ca"), ("Galego", "gl"),
    ("Euskara", "eu"), ("Português", "pt"), ("Français", "fr"), ("Deutsch", "de"),
    ("Italiano", "it"), ("中文", "zh"), ("日本語", "ja"), ("Русский", "ru"),
    ("العربية", "ar"), ("Türkçe", "tr"),
)
KEYBOARD_LAYOUTS = (
    ("English (US)", "us"), ("English (US, international)", "us-intl"),
    ("Español", "es"), ("Català", "ca"), ("Galego", "gl"), ("Euskara", "eu"),
    ("Français", "fr"), ("Deutsch", "de"), ("Italiano", "it"), ("Português", "pt"),
    ("Português (Brasil)", "br"), ("Русский", "ru"), ("Türkçe", "tr"),
    ("العربية", "ar"), ("日本語", "ja"), ("中文 (US físico)", "zh"),
)
MESSAGES = {
    "en": {
        "first_title": "Welcome to Feclora",
        "tagline": "Rescue, disk imaging and network deployment appliance",
        "language": "Interface language",
        "keyboard": "Keyboard layout",
        "apply_keyboard": "Apply keyboard layout",
        "continue": "Continue",
        "terminal": "Open root terminal",
        "overview": "Overview",
        "inventory": "Storage inventory",
        "operations": "Local operations",
        "apply_ok": "Keyboard layout applied.",
        "apply_error": "Could not apply keyboard layout:",
    },
    "es": {
        "first_title": "Bienvenido a Feclora",
        "tagline": "Sistema de rescate, imágenes de disco y despliegue en red",
        "language": "Idioma de la interfaz",
        "keyboard": "Distribución del teclado",
        "apply_keyboard": "Aplicar distribución del teclado",
        "continue": "Continuar",
        "terminal": "Abrir terminal root",
        "overview": "Inicio",
        "inventory": "Inventario de almacenamiento",
        "operations": "Operaciones locales",
        "apply_ok": "Distribución del teclado aplicada.",
        "apply_error": "No se pudo aplicar la distribución del teclado:",
    },
}


def _flatten_devices(devices: Any) -> list[dict[str, Any]]:
    if not isinstance(devices, list):
        return []
    flattened: list[dict[str, Any]] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        flattened.append(device)
        flattened.extend(_flatten_devices(device.get("children")))
    return flattened


def _flatten_logical_volumes(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    devices = _flatten_devices(inventory.get("devices"))
    groups = inventory.get("volume_topology", {}).get("volume_groups", [])
    volumes = [volume for group in groups if group.get("status") == "healthy"
               for volume in group.get("logical_volumes", [])]
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
            identity = volume.get("major_minor")
            size = volume.get("size_bytes")
            if (volume.get("hidden") or volume.get("snapshot") or not identity
                    or identity_counts.get(identity) != 1
                    or not isinstance(size, int) or size <= 0
                    or volume.get("health") not in (None, "", "-", "ok", "healthy")):
                continue
            matches = [device for device in devices if device.get("major_minor") == identity]
            if len(matches) == 1:
                result.append({
                    **matches[0],
                    "path": volume.get("path"),
                    "lvm_name": volume.get("name"),
                    "size_bytes": size,
                })
    return result


class FecloraTUI(App[None]):
    """Initial migration shell; workflows are being ported screen by screen."""

    TITLE = "Feclora"
    SUB_TITLE = "Sistema de rescate y despliegue"
    CSS = """
    #layout {
        height: 1fr;
    }
    #navigation {
        width: 32;
        min-width: 24;
        border-right: round $primary;
        padding: 1;
    }
    #content {
        width: 1fr;
        padding: 1 2;
    }
    #page-title {
        text-style: bold;
        padding-bottom: 1;
    }
    #page-message {
        height: auto;
        padding-bottom: 1;
    }
    #inventory-table {
        height: 1fr;
    }
    #page-table {
        height: 1fr;
    }
    #operations-form {
        height: 1fr;
        overflow-y: auto;
    }
    .field-label {
        margin-top: 1;
        text-style: bold;
    }
    .nav-button {
        width: 100%;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        ("ctrl+r", "refresh_data", "Actualizar"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._status: dict[str, Any] | None = None
        self._devices: list[dict[str, Any]] = []
        self._logical_volumes: list[dict[str, Any]] = []
        self._images: list[dict[str, Any]] = []
        self._active_operation_id: str | None = None
        self._settings_error = ""
        try:
            self._language = self._load_language()
        except OSError as exc:
            self._language = "es"
            self._settings_error = f"No se pudo leer el idioma guardado: {exc}"
        self._keyboard_layout = "us"
        self._current_page = "overview"
        self._selected_page_row: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="first-run"):
            yield Static("Bienvenido a Feclora", id="first-title")
            yield Static("Sistema de rescate, imágenes de disco y despliegue en red", id="first-tagline")
            yield Static("Idioma de la interfaz", classes="field-label", id="language-label")
            yield Select(LANGUAGES, value=self._language, id="language-select")
            yield Static("Distribución del teclado", classes="field-label", id="keyboard-label")
            yield Select(KEYBOARD_LAYOUTS, value="us", id="keyboard-select")
            yield Button("Aplicar distribución del teclado", id="apply-keyboard", variant="default")
            yield Button("Continuar", id="continue", variant="primary")
            yield Button("Abrir terminal root", id="open-terminal", variant="default")
            yield Static("", id="setup-message")
        with Horizontal(id="layout"):
            with Vertical(id="navigation"):
                yield Static("Feclora · navegación", id="navigation-title")
                for page_id, label in PAGES:
                    yield Button(label, id=f"nav-{page_id}", classes="nav-button")
            with Vertical(id="content"):
                yield Static("Inicio", id="page-title")
                yield Static("Cargando estado del sistema…", id="page-message")
                yield DataTable(id="inventory-table")
                yield DataTable(id="page-table", cursor_type="row")
                yield Button("Verificar imagen seleccionada", id="page-action", variant="primary")
                yield Static("", id="page-action-result")
                with Vertical(id="operations-form"):
                    yield Static("Operaciones locales", classes="field-label")
                    yield Select(OPERATIONS, value="capture_disk", id="operation-type")
                    yield Static("Dispositivo de origen", classes="field-label", id="source-label")
                    yield Select([("Selecciona un dispositivo…", "")], value="", id="source-device")
                    yield Static("Dispositivo de destino", classes="field-label", id="target-label")
                    yield Select([("Selecciona un dispositivo…", "")], value="", id="target-device")
                    yield Static("Imagen existente", classes="field-label", id="existing-image-label")
                    yield Select([("Selecciona una imagen…", "")], value="", id="existing-image")
                    yield Static("Identificador de la nueva imagen", classes="field-label", id="new-image-label")
                    yield Input(placeholder="letras, números, punto, guion o guion bajo", id="new-image-id")
                    yield Static("Formato de imagen", classes="field-label", id="format-label")
                    yield Select([("RAW de Feclora", "raw"), ("QCOW2", "qcow2")], value="raw", id="image-format")
                    yield Static("Compresión", classes="field-label", id="compression-label")
                    yield Select(COMPRESSION, value="zstd", id="compression")
                    yield Button("Cifrar artefactos con age", id="encrypt-toggle", variant="default")
                    yield Static("", id="confirmation-prompt")
                    yield Input(placeholder="Escribe la frase exacta de confirmación", id="confirmation")
                    yield Button("Iniciar operación", id="operation-start", variant="primary")
                    yield Button("Cancelar operación", id="operation-cancel", variant="error", disabled=True)
                    yield ProgressBar(total=100, show_eta=False, id="operation-progress")
                    yield Static("", id="operation-result")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#layout", Horizontal).display = False
        table = self.query_one("#inventory-table", DataTable)
        table.add_columns("Dispositivo", "Tipo", "Tamaño", "Modelo", "Sistema de archivos", "Montajes")
        table.display = False
        self.query_one("#page-table", DataTable).display = False
        self.query_one("#page-action", Button).display = False
        self.query_one("#page-action", Button).disabled = True
        self.query_one("#operations-form", Vertical).display = False
        self.query_one("#operation-progress", ProgressBar).display = False
        self._apply_language()
        if self._settings_error:
            self.query_one("#setup-message", Static).update(self._settings_error)
        try:
            current = await call_feclora("get_keyboard_layout")
            layout = current.get("layout")
            if any(value == layout for _, value in KEYBOARD_LAYOUTS):
                self._keyboard_layout = layout
                self.query_one("#keyboard-select", Select).value = layout
        except TUIAPIError as exc:
            self.query_one("#setup-message", Static).update(f"No se pudo leer el teclado actual: {exc}")
        await self._update_operation_fields()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-keyboard":
            await self.apply_keyboard_layout()
            return
        if event.button.id == "continue":
            self._language = str(self.query_one("#language-select", Select).value)
            try:
                self._save_language(self._language)
            except OSError as exc:
                self.query_one("#setup-message", Static).update(f"No se pudo guardar el idioma: {exc}")
            self.query_one("#first-run", Vertical).display = False
            self.query_one("#layout", Horizontal).display = True
            await self.refresh_data()
            return
        if event.button.id == "open-terminal":
            try:
                await call_feclora("open_root_terminal")
                self.query_one("#setup-message", Static).update("Solicitud de terminal root enviada.")
            except TUIAPIError as exc:
                self.query_one("#setup-message", Static).update(f"No se pudo abrir la terminal root: {exc}")
            return
        if event.button.id == "page-action":
            await self.run_page_action()
            return
        if event.button.id == "encrypt-toggle":
            event.button.variant = "success" if event.button.variant == "default" else "default"
            return
        if event.button.id == "operation-start":
            await self.run_operation()
            return
        if event.button.id == "operation-cancel":
            await self.cancel_operation()
            return
        page_id = (event.button.id or "").removeprefix("nav-")
        page = next((item for item in PAGES if item[0] == page_id), None)
        if page is None:
            return
        self._current_page = page_id
        self._selected_page_row = None
        self.query_one("#page-title", Static).update(page[1])
        table = self.query_one("#inventory-table", DataTable)
        page_table = self.query_one("#page-table", DataTable)
        operation_form = self.query_one("#operations-form", Vertical)
        table.display = page_id == "inventory"
        page_table.display = page_id not in {"overview", "inventory", "operations"}
        self.query_one("#page-action", Button).display = False
        self.query_one("#page-action", Button).disabled = True
        page_table.clear(columns=True)
        self.query_one("#page-action-result", Static).update("")
        operation_form.display = page_id == "operations"
        if page_id == "overview":
            await self.refresh_data()
        elif page_id == "inventory":
            await self.refresh_inventory()
        elif page_id == "operations":
            await self.refresh_inventory()
            await self.refresh_images()
            await self._update_operation_fields()
        else:
            await self.load_page(page_id)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "language-select":
            self._language = str(event.value)
            try:
                self._save_language(self._language)
            except OSError as exc:
                self.query_one("#setup-message", Static).update(f"No se pudo guardar el idioma: {exc}")
            self._apply_language()
        elif event.select.id == "keyboard-select":
            self._keyboard_layout = str(event.value)
        elif event.select.id == "operation-type":
            await self._update_operation_fields()
        elif event.select.id in {"source-device", "target-device"}:
            self._update_confirmation_prompt()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "page-table":
            self._selected_page_row = str(event.row_key.value)
            self.query_one("#page-action", Button).disabled = self._current_page != "images"
            self.query_one("#page-action-result", Static).update(
                f"Seleccionado: {self._selected_page_row}"
            )

    async def load_page(self, page_id: str) -> None:
        table = self.query_one("#page-table", DataTable)
        message = self.query_one("#page-message", Static)
        actions: dict[str, tuple[str, tuple[str, ...], str]] = {
            "images": ("images", ("Identificador", "Tipo", "Tamaño", "Origen"), "images"),
            "restore-profiles": (
                "restore_profiles", ("Perfil", "Nombre", "Imagen", "Destino", "Expira", "Estado"),
                "restore-profiles",
            ),
            "operation-log": ("operations", ("Operación", "Estado", "Inicio", "Resumen"), "operations"),
            "remote-jobs": ("deployment_jobs", ("Trabajo", "Estado", "Clientes", "Progreso"), "jobs"),
            "deployments": ("deployment_jobs", ("Despliegue", "Estado", "Clientes", "Progreso"), "jobs"),
            "network": ("network_interfaces", ("Interfaz", "Dirección", "Servidor DHCP"), "interfaces"),
            "client-jobs": ("deployment_jobs", ("Trabajo", "Cliente", "Estado"), "jobs"),
        }
        if page_id in {"server", "system"}:
            await self.load_system_page(page_id)
            return
        if page_id == "repositories":
            await self.load_repositories_page()
            return
        config = actions.get(page_id)
        if config is None:
            message.update("Esta pantalla se está migrando a Textual.")
            return
        action, columns, key = config
        message.update(f"Cargando {self.query_one('#page-title', Static).render()}…")
        try:
            response = await call_feclora(action)
        except TUIAPIError as exc:
            message.update(f"No se pudo cargar la pantalla:\n{exc}")
            return
        table.add_columns(*columns)
        rows = response.get(key) or []
        if page_id == "images":
            for item in rows:
                identifier = item.get("image_id") or "—"
                table.add_row(
                    str(identifier), str(item.get("image_type") or "—"),
                    str(item.get("source_size_bytes") or "—"), str(item.get("source") or "—"),
                    key=str(identifier),
                )
            self.query_one("#page-action", Button).display = bool(rows)
        elif page_id == "restore-profiles":
            for item in rows:
                profile_id = str(item.get("profile_id") or "—")
                state = "consumido" if item.get("consumed") else "disponible"
                table.add_row(
                    profile_id, str(item.get("name") or "—"),
                    str(item.get("image_manifest") or "—"), str(item.get("target_path") or "Sin coincidencia"),
                    str(item.get("expires_at") or "—"), state, key=profile_id,
                )
            if not response.get("storage_available"):
                message.update("Configura un repositorio remoto para consultar los perfiles de restauración.")
                return
        elif page_id in {"remote-jobs", "deployments"}:
            for item in rows:
                job_id = str(item.get("job_id") or "—")
                clients = item.get("clients") or {}
                table.add_row(
                    job_id, str(item.get("job_state") or "—"), str(len(clients)),
                    str(item.get("progress") or "—"), key=job_id,
                )
        elif page_id == "network":
            for item in rows:
                name = str(item.get("interface") or "—")
                table.add_row(
                    name, f"{item.get('address', '—')}/{item.get('prefix_length', '—')}",
                    str(item.get("dhcp_server") or "No detectado"), key=name,
                )
        elif page_id == "client-jobs":
            for job in rows:
                job_id = str(job.get("job_id") or "—")
                for client, details in (job.get("clients") or {}).items():
                    table.add_row(job_id, str(client), str(details.get("state") or "—"), key=f"{job_id}:{client}")
        else:
            for item in rows:
                operation_id = str(item.get("operation_id") or item.get("job_id") or "—")
                table.add_row(
                    operation_id, str(item.get("state") or item.get("status") or "—"),
                    str(item.get("started_at") or item.get("created_at") or "—"),
                    str(item.get("summary") or item.get("action") or "—"), key=operation_id,
                )
        message.update(f"Registros: {len(rows)}")

    async def load_repositories_page(self) -> None:
        table = self.query_one("#page-table", DataTable)
        message = self.query_one("#page-message", Static)
        try:
            remote = await call_feclora("remote_repositories")
            s3 = await call_feclora("s3_repositories")
        except TUIAPIError as exc:
            message.update(f"No se pudieron cargar los repositorios:\n{exc}")
            return
        table.add_columns("Tipo", "Identificador", "Nombre", "Estado")
        rows = []
        for kind, response in (("NFS/SSH", remote), ("S3", s3)):
            for item in response.get("repositories") or []:
                rows.append((kind, item))
        for kind, item in rows:
            identifier = str(item.get("id") or item.get("repository_id") or "—")
            table.add_row(
                kind, identifier, str(item.get("name") or identifier),
                str(item.get("state") or item.get("status") or "—"), key=f"{kind}:{identifier}",
            )
        message.update(f"Repositorios disponibles: {len(rows)}")

    async def load_system_page(self, page_id: str) -> None:
        table = self.query_one("#page-table", DataTable)
        message = self.query_one("#page-message", Static)
        try:
            status = await call_feclora("status")
            pxe = await call_feclora("pxe_service_status") if page_id == "server" else {}
        except TUIAPIError as exc:
            message.update(f"No se pudo cargar el estado:\n{exc}")
            return
        table.add_columns("Componente", "Estado")
        components = [
            ("Equipo", status.get("hostname")),
            ("Sistema", status.get("platform")),
            ("Servidor configurado", "Sí" if status.get("server_configured") else "No"),
            ("Cliente configurado", "Sí" if status.get("client_configured") else "No"),
        ]
        components.extend((f"Servicio {name}", state) for name, state in (status.get("services") or {}).items())
        components.extend((f"Certificado {item.get('role', '')}", item.get("status")) for item in status.get("certificate_status") or [])
        if page_id == "server":
            components.extend((f"PXE {name}", value) for name, value in (pxe.items() if isinstance(pxe, dict) else []))
        for index, (name, value) in enumerate(components):
            table.add_row(str(name), str(value or "—"), key=f"{page_id}:{index}")
        message.update("Estado actualizado.")

    async def run_page_action(self) -> None:
        if self._current_page != "images" or not self._selected_page_row:
            return
        try:
            result = await call_feclora("verify_image", {"image_id": self._selected_page_row})
        except TUIAPIError as exc:
            self.query_one("#page-action-result", Static).update(f"Error al verificar la imagen: {exc}")
        else:
            self.query_one("#page-action-result", Static).update(
                f"Verificación: {json.dumps(result, ensure_ascii=False)}"
            )

    async def action_refresh_data(self) -> None:
        await self.refresh_data()

    @staticmethod
    def _language_path() -> Path:
        home = Path(os.environ.get("HOME", str(Path.home())))
        return home / ".config/feclora/language"

    @classmethod
    def _load_language(cls) -> str:
        try:
            language = cls._language_path().read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "es"
        return language if language in {code for _, code in LANGUAGES} else "es"

    @classmethod
    def _save_language(cls, language: str) -> None:
        path = cls._language_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(language + "\n", encoding="utf-8")
        path.chmod(0o600)

    def _text(self, key: str) -> str:
        return MESSAGES.get(self._language, MESSAGES["en"]).get(key, MESSAGES["en"].get(key, key))

    def _apply_language(self) -> None:
        self.title = "Feclora"
        self.query_one("#first-title", Static).update(self._text("first_title"))
        self.query_one("#first-tagline", Static).update(self._text("tagline"))
        self.query_one("#language-label", Static).update(self._text("language"))
        self.query_one("#keyboard-label", Static).update(self._text("keyboard"))
        self.query_one("#apply-keyboard", Button).label = self._text("apply_keyboard")
        self.query_one("#continue", Button).label = self._text("continue")
        self.query_one("#open-terminal", Button).label = self._text("terminal")
        self.query_one("#navigation-title", Static).update(f"Feclora · {self._text('overview')}")
        self.query_one("#nav-overview", Button).label = self._text("overview")
        self.query_one("#nav-inventory", Button).label = self._text("inventory")
        self.query_one("#nav-operations", Button).label = self._text("operations")

    async def apply_keyboard_layout(self) -> None:
        layout = str(self.query_one("#keyboard-select", Select).value)
        try:
            await call_feclora("set_keyboard_layout", {"layout": layout})
        except TUIAPIError as exc:
            self.query_one("#setup-message", Static).update(f"{self._text('apply_error')} {exc}")
        else:
            self._keyboard_layout = layout
            self.query_one("#setup-message", Static).update(self._text("apply_ok"))

    async def _update_operation_fields(self) -> None:
        operation = str(self.query_one("#operation-type", Select).value)
        is_capture = operation.startswith("capture_")
        is_restore = operation.startswith("restore_")
        is_clone = operation.startswith("clone_")
        is_disk = operation.endswith("_disk")
        is_logical_volume = operation.endswith("_logical_volume")
        source_label = self.query_one("#source-label", Static)
        target_label = self.query_one("#target-label", Static)
        source_select = self.query_one("#source-device", Select)
        target_select = self.query_one("#target-device", Select)
        image_select = self.query_one("#existing-image", Select)
        self.query_one("#source-label", Static).display = is_capture or is_clone or operation == "restore_proportional_disk"
        source_select.display = source_label.display
        target_label.display = is_restore or is_clone
        target_select.display = target_label.display
        self.query_one("#existing-image-label", Static).display = is_restore
        image_select.display = is_restore
        self.query_one("#new-image-label", Static).display = is_capture
        self.query_one("#new-image-id", Input).display = is_capture
        self.query_one("#format-label", Static).display = operation == "capture_disk"
        self.query_one("#image-format", Select).display = operation == "capture_disk"
        self.query_one("#compression-label", Static).display = is_capture
        self.query_one("#compression", Select).display = is_capture
        self.query_one("#encrypt-toggle", Button).display = is_capture and operation != "capture_disk"
        self.query_one("#confirmation", Input).display = is_restore or is_clone
        self.query_one("#confirmation-prompt", Static).display = is_restore or is_clone
        source_devices = self._logical_volumes if is_logical_volume else [
            item for item in self._devices
            if item.get("type") == ("disk" if is_disk or operation == "restore_proportional_disk" else "part")
        ]
        target_devices = self._logical_volumes if is_logical_volume else [
            item for item in self._devices if item.get("type") == ("disk" if is_disk else "part")
        ]
        if operation in {"capture_disk", "capture_partition", "capture_logical_volume", "clone_disk", "clone_partition", "restore_proportional_disk"}:
            self._set_device_options(source_select, source_devices)
        else:
            self._set_device_options(source_select, [])
        if is_restore or is_clone:
            self._set_device_options(target_select, target_devices)
        else:
            self._set_device_options(target_select, [])
        image_type = "logical_volume" if is_logical_volume else "disk" if is_disk else "partition"
        images = [item for item in self._images if item.get("image_type") == image_type]
        image_select.set_options(
            [("Selecciona una imagen…", "")] +
            [(f"{item.get('image_id')} · {item.get('source_size_bytes', 0)} bytes", item["image_id"])
             for item in images if item.get("image_id")]
        )
        self._update_confirmation_prompt()

    @staticmethod
    def _set_device_options(select: Select, devices: list[dict[str, Any]]) -> None:
        select.set_options(
            [("Selecciona un dispositivo…", "")] +
            [(f"{item.get('path')} · {item.get('model') or item.get('type')}", item["path"])
             for item in devices if item.get("path")]
        )

    def _update_confirmation_prompt(self) -> None:
        operation = str(self.query_one("#operation-type", Select).value)
        source = str(self.query_one("#source-device", Select).value or "")
        target = str(self.query_one("#target-device", Select).value or "")
        if operation == "clone_partition" and source and target:
            phrase = f"ERASE {target} FROM {source}"
        elif (operation.startswith("restore_") or operation.startswith("clone_")) and target:
            phrase = f"ERASE {target}"
        else:
            phrase = ""
        self.query_one("#confirmation-prompt", Static).update(
            f"Operación destructiva: escribe exactamente «{phrase}»." if phrase else
            "Selecciona un destino para mostrar la frase de autorización."
        )

    async def run_operation(self) -> None:
        start_button = self.query_one("#operation-start", Button)
        start_button.disabled = True
        operation = str(self.query_one("#operation-type", Select).value)
        source = str(self.query_one("#source-device", Select).value or "")
        target = str(self.query_one("#target-device", Select).value or "")
        image_id = str(self.query_one("#existing-image", Select).value or "")
        new_image_id = self.query_one("#new-image-id", Input).value.strip()
        confirmation = self.query_one("#confirmation", Input).value
        message = self.query_one("#operation-result", Static)
        message.update("")
        try:
            if operation.startswith("capture_"):
                if not source or not new_image_id:
                    raise TUIAPIError("Selecciona el origen e indica un identificador de imagen.")
                params: dict[str, Any] = {
                    "source": source,
                    "image_id": new_image_id,
                    "compression": str(self.query_one("#compression", Select).value),
                    "encrypt": self.query_one("#encrypt-toggle", Button).variant == "success",
                }
                if operation == "capture_disk":
                    image_format = str(self.query_one("#image-format", Select).value)
                    params["image_format"] = image_format
                    if image_format == "qcow2":
                        params.update(compression="none", encrypt=False)
                elif operation == "capture_partition":
                    params["partition_id"] = new_image_id
            elif operation.startswith("restore_"):
                if not image_id or not target:
                    raise TUIAPIError("Selecciona una imagen y un destino.")
                expected = f"ERASE {target}"
                if confirmation != expected:
                    raise TUIAPIError(f"Escribe exactamente «{expected}» para autorizar el destino.")
                params = {"image_id": image_id, "target": target, "confirmation": confirmation}
                if operation == "restore_proportional_disk":
                    source_device = next((item for item in self._devices if item.get("path") == source), None)
                    target_device = next((item for item in self._devices if item.get("path") == target), None)
                    if not source_device or not target_device or not source_device.get("major_minor") or not target_device.get("major_minor"):
                        raise TUIAPIError("Actualiza el inventario y selecciona discos con identidad del kernel.")
                    if target_device.get("size_bytes", 0) >= source_device.get("size_bytes", 0):
                        raise TUIAPIError("El destino debe ser estrictamente menor que el disco de origen.")
                    params.update(
                        source=source,
                        source_major_minor=source_device["major_minor"],
                        target_major_minor=target_device["major_minor"],
                    )
            elif operation.startswith("clone_"):
                if not source or not target or source == target:
                    raise TUIAPIError("Selecciona dos dispositivos distintos.")
                expected = f"ERASE {target}" if operation == "clone_disk" else f"ERASE {target} FROM {source}"
                if confirmation != expected:
                    raise TUIAPIError(f"Escribe exactamente «{expected}» para autorizar el destino.")
                params = {"source": source, "target": target, "confirmation": confirmation}
            else:
                raise TUIAPIError("Operación Textual no reconocida.")
            accepted = await call_feclora(operation, params)
            operation_id = accepted.get("operation_id")
            if not operation_id:
                raise TUIAPIError("El backend no devolvió un identificador de operación.")
            self._active_operation_id = operation_id
            self.query_one("#operation-cancel", Button).disabled = False
            progress_bar = self.query_one("#operation-progress", ProgressBar)
            progress_bar.display = True
            message.update(f"Operación {operation_id} aceptada. Consultando progreso…")
            await self._wait_for_operation(operation_id)
        except TUIAPIError as exc:
            message.update(f"Operación fallida: {exc}")
        finally:
            start_button.disabled = False

    async def _wait_for_operation(self, operation_id: str) -> None:
        message = self.query_one("#operation-result", Static)
        progress_bar = self.query_one("#operation-progress", ProgressBar)
        while True:
            status = await call_feclora("local_operation_status", {"operation_id": operation_id})
            events = status.get("events") or []
            progress = next((event for event in reversed(events) if event.get("state") == "progress"), None)
            details = progress.get("details", {}) if progress else {}
            total = details.get("bytes_total")
            done = details.get("bytes_done", 0)
            if isinstance(total, int) and total > 0:
                progress_bar.update(total=100, progress=min(100, done * 100 / total))
            state = status.get("state", "unknown")
            message.update(f"Operación {operation_id}: {state} · {done} bytes")
            if state in {"completed", "failed", "cancelled", "interrupted"}:
                terminal = events[-1].get("details", {}) if events else {}
                if state == "completed":
                    message.update(f"Operación completada:\n{json.dumps(terminal, ensure_ascii=False, indent=2)}")
                else:
                    message.update(
                        f"Operación {state}: {terminal.get('error') or terminal.get('reason') or 'consulta el registro de operaciones'}"
                    )
                self._active_operation_id = None
                self.query_one("#operation-cancel", Button).disabled = True
                await self.refresh_data()
                return
            await asyncio.sleep(1.5)

    async def cancel_operation(self) -> None:
        operation_id = self._active_operation_id
        if not operation_id:
            return
        try:
            await call_feclora("cancel_local_operation", {"operation_id": operation_id})
            self.query_one("#operation-result", Static).update(
                "Cancelación solicitada. Una operación de escritura puede haber dejado el destino parcialmente modificado."
            )
        except TUIAPIError as exc:
            self.query_one("#operation-result", Static).update(f"No se pudo cancelar: {exc}")

    async def refresh_data(self) -> None:
        message = self.query_one("#page-message", Static)
        message.update("Consultando el estado local…")
        try:
            self._status = await call_feclora("status")
        except TUIAPIError as exc:
            message.update(f"No se pudo leer el estado del sistema:\n{exc}")
            return
        status = self._status
        message.update(
            f"Equipo: {status.get('hostname', '—')}\n"
            f"Sistema: {status.get('platform', '—')}\n"
            f"Servidor configurado: {'sí' if status.get('server_configured') else 'no'}\n"
            f"Cliente configurado: {'sí' if status.get('client_configured') else 'no'}\n\n"
            "Use Tab y las flechas para navegar; Enter activa el elemento enfocado."
        )

    async def refresh_inventory(self) -> None:
        message = self.query_one("#page-message", Static)
        message.update("Leyendo inventario de almacenamiento…")
        try:
            inventory = await call_feclora("inventory")
        except TUIAPIError as exc:
            message.update(f"No se pudo leer el inventario:\n{exc}")
            return
        table = self.query_one("#inventory-table", DataTable)
        table.clear()
        devices = _flatten_devices(inventory.get("devices"))
        self._devices = devices
        self._logical_volumes = _flatten_logical_volumes(inventory)
        await self._update_operation_fields()
        for device in devices:
            table.add_row(
                str(device.get("path") or "—"),
                str(device.get("type") or "—"),
                str(device.get("size_bytes") or "—"),
                str(device.get("model") or "—"),
                str(device.get("filesystem") or "—"),
                ", ".join(device.get("mountpoints") or []) or "—",
            )
        message.update(f"Dispositivos detectados: {len(devices)}")

    async def refresh_images(self) -> None:
        try:
            response = await call_feclora("images")
        except TUIAPIError as exc:
            self.query_one("#operation-result", Static).update(f"No se pudieron cargar las imágenes: {exc}")
            self._images = []
        else:
            self._images = response.get("images") or []
        await self._update_operation_fields()


def main() -> None:
    FecloraTUI().run()


if __name__ == "__main__":
    main()
