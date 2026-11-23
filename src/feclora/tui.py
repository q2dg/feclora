"""Keyboard-first Textual interface for the Feclora Live appliance."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
from pathlib import Path
from typing import Any
import uuid

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import Button, DataTable, Footer, Header, Input, ProgressBar, Select, Static, TextArea

from feclora.tui_api import TUIAPIError, call_feclora

CLASSIC_THEME = Theme(
    name="feclora-classic",
    primary="#00aaaa",
    secondary="#55ffff",
    warning="#ffff55",
    error="#ff5555",
    success="#55ff55",
    accent="#ffff55",
    foreground="#ffffff",
    background="#000080",
    surface="#000088",
    panel="#000055",
    boost="#0000aa",
    dark=True,
    luminosity_spread=0,
    text_alpha=1,
)

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
    ("Capturar disco virtual QCOW2 (P2V)", "capture_p2v"),
    ("Capturar partición", "capture_partition"),
    ("Capturar volumen lógico", "capture_logical_volume"),
    ("Capturar filesystem Stratis", "capture_stratis_filesystem"),
    ("Restaurar filesystem Stratis", "restore_stratis_filesystem"),
    ("Restaurar disco", "restore_disk"),
    ("Restaurar proporcionalmente a un disco menor", "restore_proportional_disk"),
    ("Restaurar partición", "restore_partition"),
    ("Restaurar volumen lógico", "restore_logical_volume"),
    ("Clonar disco", "clone_disk"),
    ("Clonar partición", "clone_partition"),
    ("Crear ISO de recuperación", "build_recovery_iso"),
    ("Crear paquete de despliegue", "build_deployment_bundle"),
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
    """Keyboard-first appliance interface."""

    TITLE = "Feclora"
    SUB_TITLE = "Sistema de rescate y despliegue"
    CSS = """
    Screen {
        background: $background;
        color: $text;
    }
    Header, Footer {
        background: $primary;
        color: $background;
        text-style: bold;
    }
    #layout {
        height: 1fr;
    }
    #navigation {
        width: 32;
        min-width: 24;
        background: $surface;
        color: $text;
        border-right: round $secondary;
        padding: 1;
    }
    #content {
        width: 1fr;
        background: $background;
        color: $text;
        padding: 1 2;
    }
    #page-title {
        color: $warning;
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
    .page-form {
        height: 1fr;
        overflow-y: auto;
        display: none;
    }
    .field-label {
        color: $warning;
        margin-top: 1;
        text-style: bold;
    }
    .nav-button {
        width: 100%;
        margin-bottom: 1;
        background: #c0c0c0;
        color: #000080;
        border: round #ffffff;
    }
    Button.-primary, Button.-success {
        background: $primary;
        color: #000080;
    }
    Button.-error {
        background: $error;
        color: #000080;
    }
    Button:focus, .nav-button:focus {
        background: $warning;
        color: #000080;
        text-style: bold;
    }
    Input, Select, TextArea {
        background: #c0c0c0;
        color: #000080;
    }
    Input:focus, Select:focus, TextArea:focus {
        background: #ffffff;
        color: #000080;
    }
    DataTable {
        background: $surface;
        color: $text;
        border: round $secondary;
    }
    DataTable > .datatable--header {
        background: $primary;
        color: #000080;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: $warning;
        color: #000080;
        text-style: bold;
    }
    """
    BINDINGS = [
        ("ctrl+r", "refresh_data", "Actualizar"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.register_theme(CLASSIC_THEME)
        self.theme = CLASSIC_THEME.name
        self._status: dict[str, Any] | None = None
        self._devices: list[dict[str, Any]] = []
        self._logical_volumes: list[dict[str, Any]] = []
        self._images: list[dict[str, Any]] = []
        self._image_layout: dict[str, Any] | None = None
        self._repositories: list[dict[str, Any]] = []
        self._s3_repositories: list[dict[str, Any]] = []
        self._credentials: list[dict[str, Any]] = []
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
        self._repository_selection_value = ""
        self._image_repository_selection_value = ""
        self._pxe_profile: dict[str, Any] | None = None
        self._pxe_published_answer: dict[str, Any] | None = None
        self._network_interfaces: list[dict[str, Any]] = []

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
                yield Input(placeholder="Confirmación exacta", id="page-confirmation")
                yield Static("", id="page-action-result")
                with Vertical(id="images-form", classes="page-form"):
                    yield Static("Herramientas de imágenes (solo lectura salvo extracción)", classes="field-label")
                    yield Select([("Repositorio local", "")], value="", id="image-repository-select")
                    yield Select([("Selecciona imagen de disco…", "")], value="", id="image-source-select")
                    yield Button("Inspeccionar tabla de particiones", id="image-inspect", variant="default")
                    yield Select([("Selecciona partición…", "")], value="", id="image-partition-select")
                    yield Button("Extraer imagen de partición", id="image-extract", variant="primary")
                    yield Input(value="/", placeholder="Ruta en el sistema de archivos de la imagen", id="image-browse-path")
                    yield Button("Explorar directorio (solo lectura)", id="image-browse", variant="default")
                    yield Input(placeholder="Ruta del archivo dentro de la imagen", id="image-download-path")
                    yield Button("Descargar archivo a ~/Downloads", id="image-download", variant="default")
                    yield Static("", id="image-result")
                with Vertical(id="profiles-form", classes="page-form"):
                    yield Static("Perfiles de restauración de un solo uso", classes="field-label")
                    yield Select([("Selecciona repositorio de archivos…", "")], value="", id="profile-repository")
                    yield Select([("Selecciona imagen RAW de disco…", "")], value="", id="profile-image")
                    yield Input(placeholder="Nombre del perfil", id="profile-name")
                    yield Select([("Selecciona disco con identidad estable…", "")], value="", id="profile-target")
                    yield Input(placeholder="Caducidad ISO-8601 con zona, por ejemplo 2027-01-01T12:00:00+00:00", id="profile-expiry")
                    yield Button("Crear perfil no armado", id="profile-create", variant="primary")
                    yield Static("Selecciona un perfil de la tabla y escribe la frase exacta antes de ejecutar.", classes="field-label")
                    yield Input(placeholder="ERASE /dev/sdX", id="profile-confirmation")
                    yield Button("Ejecutar restauración de un solo uso", id="profile-execute", variant="error")
                    yield Static("", id="profile-result")
                with Vertical(id="network-form", classes="page-form"):
                    yield Static("Configuración IPv4 de NetworkManager", classes="field-label")
                    yield Static("El cambio usa un checkpoint de 120 segundos; conserva acceso a la consola local.", id="network-warning")
                    yield Select([("Selecciona perfil activo…", "")], value="", id="network-profile")
                    yield Select([("Selecciona interfaz/dirección…", "")], value="", id="network-interface")
                    yield Select([("DHCP automático", "auto"), ("IPv4 manual", "manual")], value="auto", id="network-method")
                    yield Input(placeholder="Dirección IPv4", id="network-address")
                    yield Input(value="24", placeholder="Prefijo (1-32)", id="network-prefix")
                    yield Input(placeholder="Gateway (opcional)", id="network-gateway")
                    yield Input(placeholder="DNS separados por coma (opcional)", id="network-dns")
                    yield Button("Aplicar configuración de red", id="network-apply", variant="primary")
                    yield Static("", id="network-result")
                with Vertical(id="remote-jobs-form", classes="page-form"):
                    yield Static("Definición de despliegue compartido", classes="field-label")
                    yield Static("Guardar una definición no inicia servicios ni escribe discos. La ejecución requiere aprobación explícita.", id="remote-warning")
                    yield TextArea(id="remote-job-json")
                    yield Button("Validar y guardar definición JSON", id="remote-job-create", variant="primary")
                    yield Select(
                        [("Archivo JSON local", "upload"), ("URL HTTP(S)", "url"),
                         ("Repositorio configurado", "repository"), ("SCP con credenciales SSH guardadas", "scp")],
                        value="upload", id="remote-import-source",
                    )
                    yield Input(placeholder="Ruta local o URL", id="remote-import-path")
                    yield Select([("Selecciona repositorio…", "")], value="", id="remote-import-repository")
                    yield Button("Importar y validar definición", id="remote-job-import", variant="default")
                    yield Select([("Selecciona trabajo…", "")], value="", id="remote-job-select")
                    yield Select(
                        [("Consultar estado", "status"), ("Iniciar/conectar servicio", "start"),
                         ("Actualizar estado", "refresh"), ("Autorizar y ejecutar", "arm"),
                         ("Cancelar antes de autorizar", "cancel"), ("Detener servicio", "stop"),
                         ("Cerrar trabajo interrumpido para auditoría", "reconcile")],
                        value="status", id="remote-job-action",
                    )
                    yield Input(placeholder="Frase de autorización o auditoría exacta", id="remote-job-confirmation")
                    yield Button("Ejecutar acción", id="remote-job-run", variant="primary")
                    yield Static("", id="remote-job-result")
                with Vertical(id="client-jobs-form", classes="page-form"):
                    yield Static("Conectar este cliente a un trabajo remoto", classes="field-label")
                    yield Input(placeholder="Nombre DNS o dirección del servidor", id="client-server-host")
                    yield Input(placeholder="UUID del trabajo", id="client-job-id")
                    yield Select([("Selecciona interfaz/dirección activa…", "")], value="", id="client-interface")
                    yield Button("Verificar servidor e inspeccionar trabajo", id="client-inspect", variant="default")
                    yield Static("", id="client-job-details")
                    yield Select([("Selecciona destino local…", "")], value="", id="client-target")
                    yield Input(placeholder="Frase de confirmación local (ERASE… o READ…)", id="client-confirmation")
                    yield Select([("Gzip", "gzip"), ("Zstandard", "zstd"), ("LZ4", "lz4"), ("Sin compresión", "none")], value="gzip", id="client-compression")
                    yield Select([("Sin cifrado", "false"), ("Cifrar imagen con age", "true")], value="false", id="client-encrypt")
                    yield Select([("No confirmar IGMP", "false"), ("Confirmo multicast en red aislada", "true")], value="false", id="client-igmp")
                    yield Button("Iniciar servicio cliente", id="client-start", variant="primary")
                    yield Button("Consultar estado del cliente", id="client-status", variant="default")
                    yield Static("", id="client-result")
                with Vertical(id="server-form", classes="page-form"):
                    yield Static("Servidor de despliegue y arranque PXE", classes="field-label")
                    yield Select([("Selecciona interfaz/dirección activa…", "")], value="", id="server-interface")
                    yield Button("Preparar identidad TLS del servidor", id="server-bootstrap", variant="primary")
                    yield Input(placeholder="Escribe RENEW SERVER CERTIFICATE", id="server-renew-confirmation")
                    yield Button("Renovar certificado del servidor", id="server-renew", variant="default")
                    yield Input(placeholder="Escribe ROTATE SERVER TLS KEYPAIR", id="server-rotate-confirmation")
                    yield Button("Rotar clave TLS del servidor", id="server-rotate", variant="default")
                    yield Input(value="/var/lib/feclora/age-recipients", placeholder="Directorio de exportación protegido", id="server-age-directory")
                    yield Button("Exportar destinatarios age del servidor", id="server-age-export", variant="default")
                    yield Input(value="/etc/feclora/age/client-recipients.txt", placeholder="Inventario de destinatarios age del cliente", id="client-age-path")
                    yield Button("Actualizar inventario age del cliente", id="client-age-refresh", variant="default")
                    yield Static("", id="server-result")

                    yield Static("Servicios PXE / DHCP", classes="field-label")
                    yield Select([("Proxy DHCP (red existente)", "proxy"), ("Red aislada (DHCP autoritativo)", "isolated")], value="proxy", id="pxe-mode")
                    yield Input(value="192.168.50.100", placeholder="Inicio del pool DHCP", id="pxe-pool-start")
                    yield Input(value="192.168.50.200", placeholder="Fin del pool DHCP", id="pxe-pool-end")
                    yield Input(value="1h", placeholder="Duración de concesión DHCP", id="pxe-lease")
                    yield Input(placeholder="Gateway IPv4 opcional", id="pxe-gateway")
                    yield Input(placeholder="Servidor DNS IPv4 opcional", id="pxe-dns")
                    yield Input(value="8080", placeholder="Puerto HTTP PXE", id="pxe-port")
                    yield Select([("No", "false"), ("Sí, confirmo DHCP autoritativo", "true")], value="false", id="pxe-authoritative")
                    yield Input(placeholder="Máximo de clientes (opcional)", id="pxe-max-clients")
                    yield Input(placeholder="Duración máxima en segundos (opcional)", id="pxe-max-duration")
                    yield Button("Validar perfil PXE sin cambiar servicios", id="pxe-validate", variant="primary")
                    yield Button("Iniciar servicios PXE", id="pxe-start", variant="success")
                    yield Button("Detener servicios PXE", id="pxe-stop", variant="error")
                    yield Static("", id="pxe-result")

                    yield Static("Publicación de respuesta PXE autenticada", classes="field-label")
                    yield Select(
                        [("Archivo JSON local", "upload"), ("URL HTTP(S)", "url"),
                         ("Repositorio", "repository"), ("SCP con credenciales guardadas", "scp")],
                        value="upload", id="pxe-answer-source",
                    )
                    yield Input(placeholder="UUID del trabajo publicado", id="pxe-answer-job-id")
                    yield Input(placeholder="Ruta local del JSON o URL HTTP(S)", id="pxe-answer-path")
                    yield Select([("Selecciona repositorio…", "")], value="", id="pxe-answer-repository")
                    yield Input(value="deployment/feclora-deployment-job.json", placeholder="Ruta relativa dentro del repositorio", id="pxe-answer-source-path")
                    yield Button("Validar y publicar respuesta", id="pxe-answer-publish", variant="primary")
                    yield Input(placeholder="UUID para revocar", id="pxe-answer-revoke-id")
                    yield Button("Revocar respuesta publicada", id="pxe-answer-revoke", variant="error")
                    yield Static("", id="pxe-answer-result")
                    yield Static("", id="pxe-passphrase-status")
                    yield Input(password=True, placeholder="Frase age de un solo uso", id="pxe-passphrase")
                    yield Button("Enviar frase age una sola vez", id="pxe-passphrase-submit", variant="default")
                with Vertical(id="repositories-form", classes="page-form"):
                    yield Static("Repositorios remotos", classes="field-label")
                    yield Select([("Selecciona un repositorio…", "")], value="", id="repository-management-select")
                    yield Select(
                        [("Comprobar", "check_remote_repository"), ("Montar", "mount_remote_repository"),
                         ("Desmontar", "unmount_remote_repository"), ("Editar definición", "edit"),
                         ("Eliminar", "remove_remote_repository"), ("Probar S3", "check_s3_repository"),
                         ("Eliminar S3", "remove_s3_repository")],
                        value="check_remote_repository", id="repository-management-action",
                    )
                    yield Input(placeholder="Escribe REMOVE <id> para eliminar", id="repository-removal-confirmation")
                    yield Button("Ejecutar acción sobre el repositorio", id="repository-action", variant="primary")
                    yield Static("Definición de repositorio de archivos", classes="field-label")
                    yield Input(placeholder="Identificador [a-z0-9-]", id="repository-id")
                    yield Select([("SSHFS", "sshfs"), ("NFS", "nfs"), ("SMB/CIFS", "smb")], value="sshfs", id="repository-provider")
                    yield Input(placeholder="Servidor o dirección IPv4", id="repository-host")
                    yield Input(placeholder="Ruta remota o recurso compartido", value="/images", id="repository-path")
                    yield Input(placeholder="Usuario (SSHFS/SMB)", id="repository-username")
                    yield Select([("Selecciona clave SSH…", "")], value="", id="repository-identity")
                    yield Select([("Selecciona known_hosts…", "")], value="", id="repository-known-hosts")
                    yield Select([("Selecciona credencial SMB…", "")], value="", id="repository-credentials")
                    yield Input(placeholder="Puerto (opcional)", id="repository-port")
                    yield Select([("Solo lectura", "true"), ("Lectura/escritura", "false")], value="true", id="repository-read-only")
                    yield Button("Guardar definición de repositorio", id="repository-save", variant="primary")
                    yield Static("Credenciales cifradas", classes="field-label")
                    yield Input(placeholder="ID de credencial", id="credential-id")
                    yield Select(
                        [("Clave SSH", "ssh-key"), ("known_hosts", "known-hosts"),
                         ("Credencial SMB", "smb"), ("Clave S3 JSON", "s3")],
                        value="ssh-key", id="credential-kind",
                    )
                    yield Input(placeholder="Ruta de archivo fuente protegida", id="credential-source")
                    yield Select([("No", "false"), ("Sí, sustituir", "true")], value="false", id="credential-replace")
                    yield Button("Importar y cifrar credencial", id="credential-import", variant="primary")
                    yield Select([("Selecciona una credencial…", "")], value="", id="credential-select")
                    yield Input(placeholder="Escribe REMOVE <id> para eliminar", id="credential-removal-confirmation")
                    yield Button("Eliminar credencial seleccionada", id="credential-remove", variant="error")
                    yield Static("Repositorio S3", classes="field-label")
                    yield Input(placeholder="ID S3", id="s3-id")
                    yield Input(placeholder="Endpoint URL (vacío para AWS)", id="s3-endpoint")
                    yield Input(value="us-east-1", placeholder="Región", id="s3-region")
                    yield Input(placeholder="Bucket", id="s3-bucket")
                    yield Input(value="feclora", placeholder="Prefijo", id="s3-prefix")
                    yield Select([("Selecciona credencial S3…", "")], value="", id="s3-credential")
                    yield Select([("Solo lectura", "true"), ("Lectura/escritura", "false")], value="true", id="s3-read-only")
                    yield Button("Guardar repositorio S3", id="s3-save", variant="primary")
                    yield Static("Exportación P2V heredada desde S3", classes="field-label")
                    yield Select([("Selecciona S3 de origen…", "")], value="", id="p2v-source-repository")
                    yield Input(placeholder="Identificador QCOW2 heredado", id="p2v-image-id")
                    yield Select([("Repositorio local", "")], value="", id="p2v-destination-repository")
                    yield Button("Exportar bundle P2V", id="p2v-export", variant="primary")
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
                    yield Static("Repositorio de imágenes", classes="field-label", id="repository-label")
                    yield Select([("Repositorio local", "")], value="", id="repository-select")
                    yield Static("Formato de imagen", classes="field-label", id="format-label")
                    yield Select([("RAW de Feclora", "raw"), ("QCOW2", "qcow2")], value="raw", id="image-format")
                    yield Static("Compresión", classes="field-label", id="compression-label")
                    yield Select(COMPRESSION, value="zstd", id="compression")
                    yield Button("Cifrar artefactos con age", id="encrypt-toggle", variant="default")
                    yield Button("Usar cifrado con frase secreta", id="encrypt-passphrase-toggle", variant="default")
                    yield Input(placeholder="Frase secreta de cifrado", password=True, id="capture-passphrase")
                    yield Static("Ruta absoluta de la ISO Feclora base", classes="field-label", id="base-iso-label")
                    yield Input(placeholder="/home/feclora/Downloads/feclora-live.iso", id="base-iso")
                    yield Static("WWN del disco destino (opcional si se indica serie)", classes="field-label", id="target-wwn-label")
                    yield Input(id="target-wwn")
                    yield Static("Número de serie del disco destino", classes="field-label", id="target-serial-label")
                    yield Input(id="target-serial")
                    yield Static("Nombre de carpeta del paquete", classes="field-label", id="bundle-name-label")
                    yield Input(value="fleet-deployment-bundle", id="bundle-name")
                    yield Static("JSON DeploymentJob compartido", classes="field-label", id="deployment-job-label")
                    yield TextArea(id="deployment-job")
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
        self.query_one("#page-confirmation", Input).display = False
        self.query_one("#images-form", Vertical).display = False
        self.query_one("#profiles-form", Vertical).display = False
        self.query_one("#network-form", Vertical).display = False
        self.query_one("#remote-jobs-form", Vertical).display = False
        self.query_one("#client-jobs-form", Vertical).display = False
        self.query_one("#server-form", Vertical).display = False
        self.query_one("#pxe-start", Button).disabled = True
        self.query_one("#pxe-passphrase", Input).display = False
        self.query_one("#pxe-passphrase-submit", Button).display = False
        self.query_one("#pxe-answer-repository", Select).display = False
        self.query_one("#pxe-answer-source-path", Input).display = False
        self._update_pxe_fields()
        self.query_one("#operations-form", Vertical).display = False
        self.query_one("#repositories-form", Vertical).display = False
        self.query_one("#operation-progress", ProgressBar).display = False
        self.query_one("#capture-passphrase", Input).display = False
        self.query_one("#encrypt-passphrase-toggle", Button).display = False
        self._apply_language()
        if self._settings_error:
            self.query_one("#setup-message", Static).update(self._settings_error)
        self.run_worker(
            self._load_startup_keyboard_layout(),
            name="startup-keyboard-layout",
            group="startup",
        )
        self._update_repository_fields()
        self.call_after_refresh(self._report_boot_rendered)

    async def _load_startup_keyboard_layout(self) -> None:
        try:
            current = await call_feclora("get_keyboard_layout")
            layout = current.get("layout")
            if any(value == layout for _, value in KEYBOARD_LAYOUTS):
                self._keyboard_layout = layout
                self.query_one("#keyboard-select", Select).value = layout
        except TUIAPIError as exc:
            self.query_one("#setup-message", Static).update(f"No se pudo leer el teclado actual: {exc}")

    def _report_boot_rendered(self) -> None:
        if Path("/dev/virtio-ports/org.feclora.boot-smoke").exists():
            Path("/run/feclora-tui/ready").write_text("rendered\n", encoding="ascii")

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
        if event.button.id == "repository-action":
            await self.run_repository_action()
            return
        if event.button.id == "image-inspect":
            await self.inspect_image_layout()
            return
        if event.button.id == "image-extract":
            await self.extract_partition_image()
            return
        if event.button.id == "image-browse":
            await self.browse_image_directory()
            return
        if event.button.id == "image-download":
            await self.download_image_file()
            return
        if event.button.id == "profile-create":
            await self.create_restore_profile()
            return
        if event.button.id == "profile-execute":
            await self.execute_restore_profile()
            return
        if event.button.id == "network-apply":
            await self.apply_network_profile()
            return
        if event.button.id == "remote-job-create":
            await self.create_remote_job()
            return
        if event.button.id == "remote-job-import":
            await self.import_remote_job()
            return
        if event.button.id == "remote-job-run":
            await self.run_remote_job_action()
            return
        if event.button.id == "client-inspect":
            await self.inspect_client_job()
            return
        if event.button.id == "client-start":
            await self.start_client_job()
            return
        if event.button.id == "client-status":
            await self.refresh_client_job_status()
            return
        if event.button.id == "server-bootstrap":
            await self.bootstrap_server()
            return
        if event.button.id == "server-renew":
            await self.renew_server_certificate()
            return
        if event.button.id == "server-rotate":
            await self.rotate_server_keypair()
            return
        if event.button.id == "server-age-export":
            await self.export_server_age_recipients()
            return
        if event.button.id == "client-age-refresh":
            await self.refresh_client_age_recipients()
            return
        if event.button.id == "pxe-validate":
            await self.validate_pxe_profile()
            return
        if event.button.id == "pxe-start":
            await self.start_pxe_services()
            return
        if event.button.id == "pxe-stop":
            await self.stop_pxe_services()
            return
        if event.button.id == "pxe-answer-publish":
            await self.publish_pxe_answer()
            return
        if event.button.id == "pxe-answer-revoke":
            await self.revoke_pxe_answer()
            return
        if event.button.id == "pxe-passphrase-submit":
            await self.submit_pxe_passphrase()
            return
        if event.button.id == "repository-save":
            await self.save_remote_repository()
            return
        if event.button.id == "credential-import":
            await self.import_credential()
            return
        if event.button.id == "credential-remove":
            await self.remove_credential()
            return
        if event.button.id == "s3-save":
            await self.save_s3_repository()
            return
        if event.button.id == "p2v-export":
            await self.export_p2v()
            return
        if event.button.id == "encrypt-toggle":
            event.button.variant = "success" if event.button.variant == "default" else "default"
            self.query_one("#encrypt-passphrase-toggle", Button).variant = "default"
            self.query_one("#capture-passphrase", Input).value = ""
            await self._update_operation_fields()
            return
        if event.button.id == "encrypt-passphrase-toggle":
            event.button.variant = "success" if event.button.variant == "default" else "default"
            self.query_one("#encrypt-toggle", Button).variant = "default"
            self.query_one("#capture-passphrase", Input).value = ""
            await self._update_operation_fields()
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
        repository_form = self.query_one("#repositories-form", Vertical)
        images_form = self.query_one("#images-form", Vertical)
        profiles_form = self.query_one("#profiles-form", Vertical)
        network_form = self.query_one("#network-form", Vertical)
        remote_jobs_form = self.query_one("#remote-jobs-form", Vertical)
        client_jobs_form = self.query_one("#client-jobs-form", Vertical)
        server_form = self.query_one("#server-form", Vertical)
        table.display = page_id == "inventory"
        page_table.display = page_id not in {"overview", "inventory", "operations", "network", "client-jobs"}
        self.query_one("#page-action", Button).display = False
        self.query_one("#page-action", Button).disabled = True
        self.query_one("#page-confirmation", Input).display = False
        page_table.clear(columns=True)
        self.query_one("#page-action-result", Static).update("")
        operation_form.display = page_id == "operations"
        repository_form.display = page_id == "repositories"
        images_form.display = page_id == "images"
        profiles_form.display = page_id == "restore-profiles"
        network_form.display = page_id == "network"
        remote_jobs_form.display = page_id == "remote-jobs"
        client_jobs_form.display = page_id == "client-jobs"
        server_form.display = page_id == "server"
        if page_id == "overview":
            await self.refresh_data()
        elif page_id == "inventory":
            await self.refresh_inventory()
        elif page_id == "operations":
            await self.refresh_inventory()
            await self.refresh_repositories()
            await self.refresh_images()
            await self._update_operation_fields()
        elif page_id == "images":
            await self.load_images_page()
        elif page_id == "restore-profiles":
            await self.load_restore_profiles_page()
        elif page_id == "network":
            await self.load_network_page()
        elif page_id == "remote-jobs":
            await self.load_remote_jobs_page()
        elif page_id == "client-jobs":
            await self.load_client_jobs_page()
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
        elif event.select.id == "repository-select":
            if isinstance(event.value, str):
                if event.value == self._repository_selection_value:
                    return
                self._repository_selection_value = event.value
                await self.refresh_images(event.value)
                await self._update_operation_fields()
        elif event.select.id == "repository-provider":
            self._update_repository_fields()
        elif event.select.id == "repository-management-select":
            self.query_one("#repository-removal-confirmation", Input).value = ""
        elif event.select.id == "image-repository-select":
            selected = event.value if isinstance(event.value, str) else ""
            if selected == self._image_repository_selection_value:
                return
            self._image_repository_selection_value = selected
            await self.refresh_images(selected)
            await self._update_image_options()
            await self.load_image_table()
        elif event.select.id == "image-source-select":
            await self.inspect_image_layout()
        elif event.select.id == "profile-repository":
            selected = event.value if isinstance(event.value, str) else ""
            if selected != getattr(self, "_profile_repository_value", None):
                await self.load_restore_profiles_page(refresh_inputs=False)
        elif event.select.id == "network-method":
            self._update_network_fields()
        elif event.select.id == "network-profile":
            self._update_network_interface_options()
        elif event.select.id == "remote-job-select":
            self.query_one("#remote-job-confirmation", Input).value = ""
        elif event.select.id == "client-interface":
            self.query_one("#client-job-details", Static).update("")
        elif event.select.id == "client-target":
            self._update_client_confirmation()
        elif event.select.id == "pxe-mode":
            self._pxe_profile = None
            self.query_one("#pxe-start", Button).disabled = True
            self._update_pxe_fields()
        elif event.select.id in {"server-interface", "pxe-authoritative"}:
            self._pxe_profile = None
            self.query_one("#pxe-start", Button).disabled = True
        elif event.select.id == "pxe-answer-source":
            source = str(event.value)
            self.query_one("#pxe-answer-path", Input).display = source in {"upload", "url"}
            self.query_one("#pxe-answer-repository", Select).display = source in {"repository", "scp"}
            self.query_one("#pxe-answer-source-path", Input).display = source in {"repository", "scp"}
        elif event.select.id in {"source-device", "target-device"}:
            self._update_confirmation_prompt()
        elif event.select.id == "existing-image":
            self._update_confirmation_prompt()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "new-image-id":
            self._update_confirmation_prompt()
        elif event.input.id in {
            "pxe-pool-start", "pxe-pool-end", "pxe-lease", "pxe-gateway",
            "pxe-dns", "pxe-port", "pxe-max-clients", "pxe-max-duration",
        }:
            self._pxe_profile = None
            self.query_one("#pxe-start", Button).disabled = True

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "page-table":
            self._selected_page_row = str(event.row_key.value)
            action = self.query_one("#page-action", Button)
            if self._current_page == "images":
                action.disabled = False
            elif self._current_page == "operation-log":
                operation = next(
                    (item for item in getattr(self, "_operation_history", [])
                     if item.get("operation_id") == self._selected_page_row),
                    None,
                )
                cancellable = bool(operation and operation.get("state") in {"queued", "preflight", "running"})
                action.disabled = not cancellable
                self.query_one("#page-confirmation", Input).placeholder = (
                    f"Escribe CANCEL {self._selected_page_row}" if cancellable else "La operación ya no se puede cancelar"
                )
            else:
                action.disabled = True
            self.query_one("#page-action-result", Static).update(
                f"Seleccionado: {self._selected_page_row}"
            )

    def _current_image_repository(self) -> str:
        value = self.query_one("#image-repository-select", Select).value
        return value if isinstance(value, str) else ""

    def _image_repository_options(self) -> list[tuple[str, str]]:
        options = [("Repositorio local", "")]
        options.extend(
            (f"{item.get('id')} · {item.get('provider')}", item["id"])
            for item in self._repositories
            if item.get("id") and item.get("mounted") and item.get("verified")
        )
        options.extend(
            (f"{item.get('id')} · S3", item["id"])
            for item in self._s3_repositories if item.get("id")
        )
        return options

    async def load_images_page(self) -> None:
        await self.refresh_repositories()
        repository_select = self.query_one("#image-repository-select", Select)
        current = repository_select.value
        current = current if isinstance(current, str) else ""
        options = self._image_repository_options()
        repository_select.set_options(options)
        repository_select.value = current if any(value == current for _, value in options) else ""
        self._image_repository_selection_value = (
            current if any(value == current for _, value in options) else ""
        )
        await self.refresh_images(self._current_image_repository())
        await self._update_image_options()
        await self.load_image_table()

    async def load_restore_profiles_page(self, *, refresh_inputs: bool = True) -> None:
        table = self.query_one("#page-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Perfil", "Nombre", "Imagen", "Destino", "Caduca", "Estado")
        repository_select = self.query_one("#profile-repository", Select)
        if refresh_inputs:
            await self.refresh_repositories()
            await self.refresh_inventory()
            options = [("Selecciona repositorio de archivos…", "")]
            options.extend(
                (f"{item.get('id')} · {item.get('provider')}", item["id"])
                for item in self._repositories
                if item.get("id") and item.get("mounted") and item.get("verified") and not item.get("read_only")
            )
            current = repository_select.value
            current = current if isinstance(current, str) else ""
            repository_select.set_options(options)
            repository_id = current if any(value == current for _, value in options) else ""
            repository_select.value = repository_id
            self.query_one("#profile-target", Select).set_options(
                [("Selecciona disco con identidad estable…", "")] +
                [(f"{item.get('path')} · {item.get('model') or 'Disco'} · {item.get('wwn') or item.get('serial')}",
                  str(item.get("path")))
                 for item in self._devices if item.get("type") == "disk" and (item.get("wwn") or item.get("serial"))]
            )
        else:
            repository_id = repository_select.value
            repository_id = repository_id if isinstance(repository_id, str) else ""
        self._profile_repository_value = repository_id
        image_select = self.query_one("#profile-image", Select)
        profile_list: list[dict[str, Any]] = []
        if repository_id:
            try:
                images = await call_feclora("repository_images", {"repository_id": repository_id})
                image_select.set_options(
                    [("Selecciona imagen RAW de disco…", "")] +
                    [(f"{item.get('image_id')} · {item.get('source_size_bytes', 0)} bytes", item["image_id"])
                     for item in images.get("images", [])
                     if item.get("image_type") == "disk" and item.get("image_format") == "raw"]
                )
                response = await call_feclora("restore_profiles", {"repository_id": repository_id})
                profile_list = response.get("profiles") or []
            except TUIAPIError as exc:
                self.query_one("#profile-result", Static).update(f"No se pudieron cargar los perfiles: {exc}")
                return
        else:
            image_select.set_options([("Selecciona imagen RAW de disco…", "")])
        self._restore_profiles = profile_list
        for item in profile_list:
            profile_id = str(item.get("profile_id") or "—")
            state = "consumido" if item.get("consumed") else "disponible"
            table.add_row(
                profile_id, str(item.get("name") or "—"),
                str(item.get("image_manifest") or "—"), str(item.get("target_path") or "Sin coincidencia"),
                str(item.get("expires_at") or "—"), state, key=profile_id,
            )
        self.query_one("#page-message", Static).update(
            f"Perfiles: {len(profile_list)}. Se requieren repositorios de archivos persistentes montados y verificados."
        )

    async def create_restore_profile(self) -> None:
        repository_id = self.query_one("#profile-repository", Select).value
        image_id = self.query_one("#profile-image", Select).value
        target_path = self.query_one("#profile-target", Select).value
        profile_name = self.query_one("#profile-name", Input).value.strip()
        expires_at = self.query_one("#profile-expiry", Input).value.strip()
        if not all(isinstance(value, str) and value for value in (repository_id, image_id, target_path, profile_name, expires_at)):
            self.query_one("#profile-result", Static).update("Completa repositorio, imagen, nombre, disco destino y caducidad.")
            return
        try:
            target = next(item for item in self._devices if item.get("path") == target_path and item.get("type") == "disk")
        except StopIteration:
            self.query_one("#profile-result", Static).update("Actualiza el inventario; el disco seleccionado ya no está disponible.")
            return
        if not target.get("wwn") and not target.get("serial"):
            self.query_one("#profile-result", Static).update("El disco debe tener WWN o número de serie para vincular el perfil.")
            return
        try:
            from datetime import datetime
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                raise ValueError("la fecha debe incluir una zona horaria")
        except ValueError as exc:
            self.query_one("#profile-result", Static).update(f"Caducidad ISO-8601 no válida: {exc}")
            return
        try:
            result = await call_feclora("create_restore_profile", {
                "name": profile_name,
                "image_id": image_id,
                "target_wwn": target.get("wwn"),
                "target_serial": target.get("serial"),
                "expires_at": expiry.isoformat(),
                "repository_id": repository_id,
            })
        except TUIAPIError as exc:
            self.query_one("#profile-result", Static).update(f"No se pudo crear el perfil: {exc}")
            return
        self.query_one("#profile-result", Static).update(
            f"Perfil guardado, no armado ni ejecutado: {result.get('profile_id', '—')}"
        )
        await self.load_restore_profiles_page()

    async def execute_restore_profile(self) -> None:
        profile_id = self._selected_page_row
        profile = next((item for item in getattr(self, "_restore_profiles", []) if item.get("profile_id") == profile_id), None)
        if not profile:
            self.query_one("#profile-result", Static).update("Selecciona un perfil de la tabla.")
            return
        target = profile.get("target_path")
        confirmation = self.query_one("#profile-confirmation", Input).value
        expected = f"ERASE {target}" if target else ""
        if profile.get("consumed") or not target or confirmation != expected:
            self.query_one("#profile-result", Static).update(
                f"El perfil debe estar disponible y el destino detectado debe confirmarse con «{expected}»."
            )
            return
        repository_id = self.query_one("#profile-repository", Select).value
        try:
            accepted = await call_feclora("execute_restore_profile", {
                "profile_id": profile_id,
                "target": target,
                "confirmation": confirmation,
                "repository_id": repository_id,
            })
            operation_id = accepted.get("operation_id")
            if not operation_id:
                raise TUIAPIError("El backend no devolvió un identificador de operación.")
            self.query_one("#profile-result", Static).update(
                f"Restauración aceptada por el worker duradero: {operation_id}."
            )
            await self._wait_for_operation(operation_id, "#profile-result")
            self.query_one("#profile-confirmation", Input).value = ""
            await self.load_restore_profiles_page()
        except TUIAPIError as exc:
            self.query_one("#profile-result", Static).update(f"No se pudo ejecutar el perfil: {exc}")

    async def load_network_page(self) -> None:
        try:
            profiles, interfaces = await asyncio.gather(
                call_feclora("network_connection_profiles"),
                call_feclora("network_interfaces"),
            )
        except TUIAPIError as exc:
            self.query_one("#network-result", Static).update(f"No se pudo cargar la red: {exc}")
            return
        self._network_profiles = profiles.get("profiles") or []
        self._network_interfaces = interfaces.get("interfaces") or []
        self.query_one("#network-profile", Select).set_options(
            [("Selecciona perfil activo…", "")] +
            [(f"{item.get('name') or item.get('id')} · {item.get('device') or 'sin interfaz'}", str(item.get("uuid") or ""))
             for item in self._network_profiles if item.get("uuid") and item.get("active") and item.get("device")]
        )
        self._update_network_interface_options()
        self.query_one("#page-message", Static).update(
            f"Perfiles NetworkManager: {len(self._network_profiles)} · direcciones IPv4 activas: {len(self._network_interfaces)}"
        )
        self._update_network_fields()

    def _update_network_interface_options(self) -> None:
        profile_uuid = self.query_one("#network-profile", Select).value
        profile = next(
            (item for item in getattr(self, "_network_profiles", [])
             if item.get("uuid") == profile_uuid and item.get("active")),
            None,
        )
        interface_name = profile.get("device") if profile else None
        options = [("Selecciona interfaz/dirección…", "")]
        options.extend(
            (f"{item.get('interface')} · {item.get('address')}/{item.get('prefix_length')}", str(item.get("binding")))
            for item in getattr(self, "_network_interfaces", [])
            if item.get("binding") and item.get("interface") == interface_name
        )
        select = self.query_one("#network-interface", Select)
        current = select.value
        current = current if isinstance(current, str) else ""
        select.set_options(options)
        select.value = current if any(value == current for _, value in options) else ""

    def _update_network_fields(self) -> None:
        manual = self.query_one("#network-method", Select).value == "manual"
        for widget_id in ("network-address", "network-prefix", "network-gateway", "network-dns"):
            self.query_one(f"#{widget_id}", Input).display = manual

    async def apply_network_profile(self) -> None:
        profile_uuid = self.query_one("#network-profile", Select).value
        binding = self.query_one("#network-interface", Select).value
        profile = next((item for item in getattr(self, "_network_profiles", []) if item.get("uuid") == profile_uuid), None)
        interface = next((item for item in getattr(self, "_network_interfaces", []) if item.get("binding") == binding), None)
        if (not profile or not profile.get("device") or not profile.get("active") or not interface
                or interface.get("interface") != profile.get("device")):
            self.query_one("#network-result", Static).update("Selecciona un perfil activo asociado a una interfaz y una dirección del host.")
            return
        method = str(self.query_one("#network-method", Select).value)
        params: dict[str, Any] = {
            "uuid": profile_uuid,
            "interface": interface["interface"],
            "method": method,
            "address": None,
            "prefix_length": None,
            "gateway": None,
            "dns": [],
            "rollback_timeout": 120,
        }
        if method == "manual":
            address_text = self.query_one("#network-address", Input).value.strip()
            gateway_text = self.query_one("#network-gateway", Input).value.strip()
            try:
                address = ipaddress.IPv4Address(address_text)
                prefix = int(self.query_one("#network-prefix", Input).value)
                if not 1 <= prefix <= 32:
                    raise ValueError("el prefijo debe estar entre 1 y 32")
                gateway = ipaddress.IPv4Address(gateway_text) if gateway_text else None
                dns = [
                    str(ipaddress.IPv4Address(value.strip()))
                    for value in self.query_one("#network-dns", Input).value.split(",")
                    if value.strip()
                ]
            except ValueError as exc:
                self.query_one("#network-result", Static).update(f"Dirección, prefijo, gateway o DNS no válido: {exc}")
                return
            params.update(address=str(address), prefix_length=prefix, gateway=str(gateway) if gateway else None, dns=dns)
        try:
            result = await call_feclora("apply_network_profile", params)
        except TUIAPIError as exc:
            self.query_one("#network-result", Static).update(f"No se pudo aplicar la red: {exc}")
            return
        self.query_one("#network-result", Static).update(
            str(result.get("message") or "Perfil aplicado y verificado; checkpoint de red confirmado.")
        )
        await self.load_network_page()

    async def load_remote_jobs_page(self) -> None:
        try:
            response = await call_feclora("deployment_jobs")
        except TUIAPIError as exc:
            self.query_one("#remote-job-result", Static).update(f"No se pudieron cargar los trabajos: {exc}")
            return
        self._deployment_jobs = response.get("jobs") or []
        table = self.query_one("#page-table", DataTable)
        table.clear(columns=True)
        table.add_columns("ID", "Operación", "Imagen/origen", "Destino", "Transporte", "Estado", "Clientes", "Eventos")
        for job in self._deployment_jobs:
            job_id = str(job.get("job_id") or "—")
            clients = job.get("clients") or {}
            table.add_row(
                job_id, str(job.get("operation") or "—"),
                str(job.get("source_device") if job.get("operation") == "clone" else job.get("image_id") or "—"),
                str(job.get("target_type") or "—"), str(job.get("transport") or "—"),
                str(job.get("job_state") or "—"),
                ", ".join(f"{mac}: {state.get('state', '—')}" for mac, state in clients.items()) or "No conectados",
                str(job.get("event_count") or 0), key=job_id,
            )
        self.query_one("#remote-job-select", Select).set_options(
            [("Selecciona trabajo…", "")] +
            [(f"{item.get('job_id')} · {item.get('job_state')}", str(item.get("job_id")))
             for item in self._deployment_jobs if item.get("job_id")]
        )
        repositories = [("Selecciona repositorio…", "")]
        repositories.extend(
            (f"{item.get('id')} · {item.get('provider')}", item["id"])
            for item in self._repositories if item.get("id")
        )
        repositories.extend(
            (f"{item.get('id')} · S3", item["id"])
            for item in self._s3_repositories if item.get("id")
        )
        self.query_one("#remote-import-repository", Select).set_options(repositories)
        self.query_one("#page-message", Static).update(f"Trabajos persistidos: {len(self._deployment_jobs)}.")

    async def create_remote_job(self) -> None:
        try:
            job = json.loads(self.query_one("#remote-job-json", TextArea).text)
            if not isinstance(job, dict):
                raise TUIAPIError("La definición debe ser un objeto JSON.")
            result = await call_feclora("create_deployment_job", {"job": job})
        except json.JSONDecodeError as exc:
            self.query_one("#remote-job-result", Static).update(f"JSON no válido: {exc}")
            return
        except TUIAPIError as exc:
            self.query_one("#remote-job-result", Static).update(f"No se pudo guardar el trabajo: {exc}")
            return
        self.query_one("#remote-job-result", Static).update(
            f"{result.get('message', 'Definición guardada; servicio y disco sin tocar.')}\nID: {result.get('job_id', '—')}"
        )
        await self.load_remote_jobs_page()

    async def import_remote_job(self) -> None:
        source = str(self.query_one("#remote-import-source", Select).value)
        path_or_url = self.query_one("#remote-import-path", Input).value.strip()
        request: dict[str, Any] = {"source": source}
        try:
            if source == "upload":
                if not path_or_url:
                    raise TUIAPIError("Indica la ruta local del archivo JSON.")
                payload = Path(path_or_url).expanduser().read_bytes()
                if not 1 <= len(payload) <= 64 * 1024:
                    raise TUIAPIError("El archivo debe tener entre 1 byte y 64 KiB.")
                request["answer_base64"] = base64.b64encode(payload).decode("ascii")
            elif source == "url":
                if not path_or_url:
                    raise TUIAPIError("Indica una URL HTTP o HTTPS.")
                request["url"] = path_or_url
            else:
                repository_id = self.query_one("#remote-import-repository", Select).value
                if not isinstance(repository_id, str) or not repository_id or not path_or_url:
                    raise TUIAPIError("Selecciona un repositorio y una ruta relativa.")
                request["repository_id"] = repository_id
                request["source_path"] = path_or_url
            result = await call_feclora("import_deployment_job", request)
        except (OSError, TUIAPIError) as exc:
            self.query_one("#remote-job-result", Static).update(f"No se pudo importar el trabajo: {exc}")
            return
        job = result.get("job")
        if not isinstance(job, dict):
            self.query_one("#remote-job-result", Static).update("El backend no devolvió una definición de trabajo.")
            return
        self.query_one("#remote-job-json", TextArea).text = json.dumps(job, ensure_ascii=False, indent=2) + "\n"
        self.query_one("#remote-job-result", Static).update(
            f"{result.get('message', 'Definición validada. Revísala antes de guardarla.')}\n"
            "La importación no inicia servicios ni operaciones de almacenamiento."
        )

    def _selected_remote_job(self) -> dict[str, Any] | None:
        job_id = self.query_one("#remote-job-select", Select).value
        if not isinstance(job_id, str) or not job_id:
            return None
        return next((job for job in getattr(self, "_deployment_jobs", []) if job.get("job_id") == job_id), None)

    @staticmethod
    def _deployment_arm_phrase(job: dict[str, Any]) -> str:
        job_id = str(job.get("job_id") or "")
        if job.get("operation") == "clone" and job.get("transport") == "multicast":
            return f"ARM PHYSICAL MULTICAST {job_id} FROM {job.get('source_device')} IGMP-VERIFIED"
        if job.get("transport") == "multicast":
            return f"ARM MULTICAST {job_id} IGMP-VERIFIED"
        if job.get("operation") == "clone":
            return f"ARM {job_id} AND READ {job.get('source_device')}"
        return f"ARM {job_id}"

    async def run_remote_job_action(self) -> None:
        job = self._selected_remote_job()
        if not job:
            self.query_one("#remote-job-result", Static).update("Selecciona un trabajo persistido.")
            return
        job_id = str(job["job_id"])
        action = str(self.query_one("#remote-job-action", Select).value)
        confirmation = self.query_one("#remote-job-confirmation", Input).value
        try:
            if action == "start":
                if job.get("interrupted") or job.get("job_state") != "created":
                    raise TUIAPIError("Solo se inicia el servicio de una definición nueva no interrumpida.")
                result = await call_feclora("start_deployment_service", {"job_id": job_id})
            elif action == "refresh":
                result = await call_feclora("deployment_service_status", {"job_id": job_id})
            elif action == "status":
                result = await call_feclora("deployment_service_status", {"job_id": job_id})
            elif action == "arm":
                expected = self._deployment_arm_phrase(job)
                if job.get("job_state") != "created" or confirmation != expected:
                    raise TUIAPIError(f"El trabajo debe estar creado y requiere escribir exactamente «{expected}».")
                result = await call_feclora("arm_deployment_job", {"job_id": job_id, "confirmation": confirmation})
            elif action == "cancel":
                expected = f"CANCEL {job_id}"
                if confirmation != expected:
                    raise TUIAPIError(f"Escribe exactamente «{expected}» para cancelar antes de autorizar.")
                result = await call_feclora("cancel_deployment_job", {"job_id": job_id, "confirmation": confirmation})
            elif action == "stop":
                status = await call_feclora("deployment_service_status", {"job_id": job_id})
                running_clients = any(item.get("state") == "running" for item in status.get("clients") or [])
                if status.get("worker_active") or status.get("job_state") == "running" or running_clients:
                    raise TUIAPIError("No se detiene un worker ni una operación de cliente en curso.")
                result = await call_feclora("stop_deployment_service", {"job_id": job_id})
            elif action == "reconcile":
                expected = f"RECONCILE {job_id}"
                if not job.get("interrupted") or confirmation != expected:
                    raise TUIAPIError(f"El trabajo debe estar interrumpido y requiere escribir exactamente «{expected}».")
                result = await call_feclora("reconcile_deployment_job", {"job_id": job_id, "confirmation": confirmation})
            else:
                raise TUIAPIError("Acción de trabajo no reconocida.")
        except TUIAPIError as exc:
            self.query_one("#remote-job-result", Static).update(f"Acción no completada: {exc}")
            return
        self.query_one("#remote-job-confirmation", Input).value = ""
        self.query_one("#remote-job-result", Static).update(json.dumps(result, ensure_ascii=False, indent=2))
        await self.load_remote_jobs_page()

    async def load_client_jobs_page(self) -> None:
        await self.refresh_inventory()
        try:
            response = await call_feclora("network_interfaces")
        except TUIAPIError as exc:
            self.query_one("#client-result", Static).update(f"No se pudieron cargar las interfaces: {exc}")
            return
        self._client_network_interfaces = response.get("interfaces") or []
        self.query_one("#client-interface", Select).set_options(
            [("Selecciona interfaz/dirección activa…", "")] +
            [(f"{item.get('interface')} · {item.get('address')}", item["binding"])
             for item in self._client_network_interfaces if item.get("binding")]
        )
        self.query_one("#page-message", Static).update(
            f"Dispositivos locales: {len(self._devices)} · interfaces activas: {len(self._client_network_interfaces)}"
        )

    async def inspect_client_job(self) -> None:
        host = self.query_one("#client-server-host", Input).value.strip()
        job_id = self.query_one("#client-job-id", Input).value.strip()
        binding = self.query_one("#client-interface", Select).value
        interface = next((item for item in getattr(self, "_client_network_interfaces", []) if item.get("binding") == binding), None)
        if not host or not job_id or not interface:
            self.query_one("#client-result", Static).update("Indica servidor, UUID del trabajo e interfaz IPv4 activa.")
            return
        try:
            result = await call_feclora("inspect_remote_job", {
                "host": host,
                "job_id": job_id,
                "network_interface": interface["interface"],
                "source_address": interface["address"],
            })
        except TUIAPIError as exc:
            self._client_remote_inspection = None
            self.query_one("#client-result", Static).update(f"No se pudo autenticar/inspeccionar el servidor: {exc}")
            return
        self._client_remote_inspection = result
        job = result.get("job") or {}
        target_type = job.get("target_type")
        if target_type == "logical_volume":
            eligible = self._logical_volumes
        else:
            eligible_type = {"disk": "disk", "partition": "part"}.get(target_type)
            eligible = [item for item in self._devices if item.get("type") == eligible_type]
        self.query_one("#client-target", Select).set_options(
            [("Selecciona destino local…", "")] +
            [(f"{item.get('path')} · {item.get('model') or item.get('type')} · {item.get('size_bytes', 0)} bytes",
              str(item.get("path")))
             for item in eligible if item.get("path")]
        )
        self._update_client_confirmation()
        self.query_one("#client-result", Static).update("TLS e identidad del servidor verificados; no se inició ningún trabajo.")

    def _update_client_confirmation(self) -> None:
        inspection = getattr(self, "_client_remote_inspection", None)
        if not isinstance(inspection, dict) or not isinstance(inspection.get("job"), dict):
            return
        job = inspection["job"]
        target = self.query_one("#client-target", Select).value
        target = target if isinstance(target, str) else ""
        phrase = (
            f"ERASE {target}" if job.get("operation") in {"restore", "clone"}
            else f"READ {target} TO {inspection.get('server_identity')}"
        ) if target else ""
        self.query_one("#client-job-details", Static).update(
            json.dumps({"server_identity": inspection.get("server_identity"), "job": job}, ensure_ascii=False, indent=2)
            + (f"\nConfirmación local exacta: {phrase}" if phrase else "\nSelecciona un destino para calcular la confirmación local.")
        )

    async def start_client_job(self) -> None:
        inspection = getattr(self, "_client_remote_inspection", None)
        if not isinstance(inspection, dict) or not isinstance(inspection.get("job"), dict):
            self.query_one("#client-result", Static).update("Inspecciona y autentica primero el trabajo del servidor.")
            return
        job = inspection["job"]
        target = self.query_one("#client-target", Select).value
        binding = self.query_one("#client-interface", Select).value
        interface = next((item for item in getattr(self, "_client_network_interfaces", []) if item.get("binding") == binding), None)
        if not isinstance(target, str) or not target or not interface:
            self.query_one("#client-result", Static).update("Selecciona un destino y la interfaz autenticada.")
            return
        phrase = (
            f"ERASE {target}" if job.get("operation") in {"restore", "clone"}
            else f"READ {target} TO {inspection.get('server_identity')}"
        )
        confirmation = self.query_one("#client-confirmation", Input).value
        if confirmation != phrase:
            self.query_one("#client-result", Static).update(f"Escribe exactamente «{phrase}» para aprobar el destino local.")
            return
        try:
            result = await call_feclora("start_client_job", {
                "host": self.query_one("#client-server-host", Input).value.strip(),
                "job_id": job["job_id"],
                "device_path": target,
                "confirmation": confirmation,
                "compression": str(self.query_one("#client-compression", Select).value),
                "image_encrypt": str(self.query_one("#client-encrypt", Select).value) == "true",
                "network_interface": interface["interface"],
                "source_address": interface["address"],
                "igmp_confirmed": (
                    str(self.query_one("#client-igmp", Select).value) == "true"
                    if job.get("transport") == "multicast" else False
                ),
            })
        except TUIAPIError as exc:
            self.query_one("#client-result", Static).update(f"No se pudo iniciar el cliente: {exc}")
            return
        self._client_remote_job_status = result
        self.query_one("#client-confirmation", Input).value = ""
        self.query_one("#client-result", Static).update(json.dumps(result, ensure_ascii=False, indent=2))

    async def refresh_client_job_status(self) -> None:
        inspection = getattr(self, "_client_remote_inspection", None)
        job = inspection.get("job") if isinstance(inspection, dict) else None
        if not isinstance(job, dict):
            self.query_one("#client-result", Static).update("Inspecciona primero el trabajo remoto.")
            return
        try:
            result = await call_feclora("client_job_status", {"job_id": job["job_id"]})
        except TUIAPIError as exc:
            self.query_one("#client-result", Static).update(f"No se pudo consultar el cliente: {exc}")
            return
        self._client_remote_job_status = result
        self.query_one("#client-result", Static).update(json.dumps(result, ensure_ascii=False, indent=2))

    async def load_image_table(self) -> None:
        table = self.query_one("#page-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Imagen", "Tipo", "Tamaño", "Cifrado", "Artefactos")
        for item in self._images:
            image_id = str(item.get("image_id") or "—")
            table.add_row(
                image_id, str(item.get("image_type") or "—"),
                str(item.get("source_size_bytes") or "—"),
                "age" if item.get("encrypted") else "Sin cifrar",
                str(item.get("artifact_count") or 0), key=image_id,
            )
        has_images = bool(self._images)
        self.query_one("#page-action", Button).display = has_images
        self.query_one("#page-action", Button).disabled = True
        self.query_one("#page-message", Static).update(f"Imágenes disponibles: {len(self._images)}")

    async def _update_image_options(self) -> None:
        self._image_layout = None
        self._browse_session_id = ""
        select = self.query_one("#image-source-select", Select)
        select.set_options(
            [("Selecciona imagen de disco…", "")] +
            [(str(item.get("image_id")), str(item["image_id"]))
             for item in self._images
             if item.get("image_id") and item.get("image_type") == "disk"]
        )
        partition_select = self.query_one("#image-partition-select", Select)
        partition_select.set_options([("Selecciona partición…", "")])
        self.query_one("#image-result", Static).update("")

    async def inspect_image_layout(self) -> None:
        image_id = self.query_one("#image-source-select", Select).value
        if not isinstance(image_id, str) or not image_id:
            return
        params: dict[str, Any] = {"image_id": image_id}
        repository_id = self._current_image_repository()
        if repository_id:
            params["repository_id"] = repository_id
        try:
            layout = await call_feclora("inspect_image_layout", params)
        except TUIAPIError as exc:
            self._image_layout = None
            self.query_one("#image-result", Static).update(f"No se pudo inspeccionar la imagen: {exc}")
            self.query_one("#image-partition-select", Select).set_options([("Selecciona partición…", "")])
            return
        partitions = layout.get("partitions") or []
        self._image_layout = layout
        self.query_one("#image-partition-select", Select).set_options(
            [("Selecciona partición…", "")] +
            [(f"{item.get('node')} · {item.get('uuid') or item.get('name') or item.get('selector')}",
              str(item.get("selector") or ""))
             for item in partitions if item.get("selector")]
        )
        self.query_one("#image-result", Static).update(
            f"{layout.get('message', 'Tabla verificada')} · {len(partitions)} particiones · "
            f"{layout.get('source_size_bytes', 0)} bytes · sector lógico "
            f"{layout.get('logical_sector_size', '—')} bytes"
        )

    def _selected_partition_index(self) -> int:
        image_id = self.query_one("#image-source-select", Select).value
        selector = self.query_one("#image-partition-select", Select).value
        if not isinstance(image_id, str) or not image_id or not isinstance(selector, str) or not selector:
            raise TUIAPIError("Selecciona una imagen de disco y una partición.")
        layout = getattr(self, "_image_layout", None)
        if not layout or layout.get("image_id") != image_id:
            raise TUIAPIError("Inspecciona la imagen seleccionada antes de continuar.")
        index = next(
            (position for position, item in enumerate(layout.get("partitions", []))
             if item.get("selector") == selector),
            None,
        )
        if index is None:
            raise TUIAPIError("La partición seleccionada ya no pertenece a la tabla verificada.")
        return index + 1

    async def extract_partition_image(self) -> None:
        try:
            partition_index = self._selected_partition_index()
            image_id = str(self.query_one("#image-source-select", Select).value)
            selector = str(self.query_one("#image-partition-select", Select).value)
            params: dict[str, Any] = {"image_id": image_id, "selector": selector}
            repository_id = self._current_image_repository()
            if repository_id:
                params["repository_id"] = repository_id
            repository = next((item for item in self._repositories if item.get("id") == repository_id), None)
            s3_repository = next((item for item in self._s3_repositories if item.get("id") == repository_id), None)
            if repository and repository.get("read_only") or s3_repository and s3_repository.get("read_only"):
                raise TUIAPIError("El repositorio seleccionado es de solo lectura.")
            accepted = await call_feclora("extract_partition_image", params)
            operation_id = accepted.get("operation_id")
            if not operation_id:
                raise TUIAPIError("El backend no devolvió un identificador de operación.")
            self.query_one("#image-result", Static).update(
                f"Extracción iniciada para partición {partition_index}, operación {operation_id}."
            )
            await self._wait_for_operation(operation_id, "#image-result")
        except TUIAPIError as exc:
            self.query_one("#image-result", Static).update(f"No se pudo extraer la partición: {exc}")

    async def browse_image_directory(self) -> None:
        try:
            partition_index = self._selected_partition_index()
        except TUIAPIError as exc:
            self.query_one("#image-result", Static).update(str(exc))
            return
        params: dict[str, Any] = {
            "image_id": str(self.query_one("#image-source-select", Select).value),
            "partition_index": partition_index,
            "path": self.query_one("#image-browse-path", Input).value.strip() or "/",
        }
        repository_id = self._current_image_repository()
        if repository_id:
            params["repository_id"] = repository_id
        if getattr(self, "_browse_session_id", ""):
            params["session_id"] = self._browse_session_id
        try:
            result = await call_feclora("browse_image", params)
        except TUIAPIError as exc:
            self._browse_session_id = ""
            self.query_one("#image-result", Static).update(f"No se pudo explorar la imagen: {exc}")
            return
        self._browse_session_id = result.get("session_id", "")
        self.query_one("#image-browse-path", Input).value = result.get("path", "/")
        entries = result.get("entries") or []
        rendered = [
            f"{item.get('kind', '—'):9} {item.get('name', '—')} "
            f"{item.get('size_bytes', '') if item.get('kind') == 'file' else ''}"
            for item in entries
        ]
        self.query_one("#image-result", Static).update(
            f"{result.get('partition', '—')} · {result.get('filesystem', '—')} · "
            f"{result.get('path', '/')}:\n" + ("\n".join(rendered) or "(directorio vacío)")
        )

    async def download_image_file(self) -> None:
        try:
            partition_index = self._selected_partition_index()
        except TUIAPIError as exc:
            self.query_one("#image-result", Static).update(str(exc))
            return
        path = self.query_one("#image-download-path", Input).value.strip()
        if not path.startswith("/") or "\x00" in path:
            self.query_one("#image-result", Static).update("Indica una ruta absoluta del archivo en la imagen.")
            return
        params: dict[str, Any] = {
            "image_id": str(self.query_one("#image-source-select", Select).value),
            "partition_index": partition_index,
            "path": path,
            "download": True,
        }
        repository_id = self._current_image_repository()
        if repository_id:
            params["repository_id"] = repository_id
        if getattr(self, "_browse_session_id", ""):
            params["session_id"] = self._browse_session_id
        try:
            result = await call_feclora("browse_image", params)
            filename = result.get("filename")
            content = result.get("content_base64")
            if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(content, str):
                raise TUIAPIError("El backend devolvió datos de descarga no válidos.")
            import base64
            data = base64.b64decode(content, validate=True)
            download_dir = Path.home() / "Downloads"
            download_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            resolved_home = Path.home().resolve()
            resolved_download_dir = download_dir.resolve(strict=True)
            if not resolved_download_dir.is_relative_to(resolved_home):
                raise TUIAPIError("La carpeta Downloads debe permanecer dentro del directorio personal.")
            destination = resolved_download_dir / filename
            with destination.open("xb") as stream:
                stream.write(data)
            self.query_one("#image-result", Static).update(f"Archivo guardado en {destination}")
        except (TUIAPIError, OSError, ValueError) as exc:
            self.query_one("#image-result", Static).update(f"No se pudo descargar el archivo: {exc}")

    async def load_page(self, page_id: str) -> None:
        table = self.query_one("#page-table", DataTable)
        table.clear(columns=True)
        self._selected_page_row = None
        self.query_one("#page-action", Button).disabled = True
        message = self.query_one("#page-message", Static)
        actions: dict[str, tuple[str, tuple[str, ...], str]] = {
            "images": ("images", ("Identificador", "Tipo", "Tamaño", "Origen"), "images"),
            "restore-profiles": (
                "restore_profiles", ("Perfil", "Nombre", "Imagen", "Destino", "Expira", "Estado"),
                "restore-profiles",
            ),
            "operation-log": ("local_operations", ("ID", "Acción", "Estado", "Último evento", "Progreso", "Detalles"), "operations"),
            "remote-jobs": ("deployment_jobs", ("Trabajo", "Estado", "Clientes", "Progreso"), "jobs"),
            "deployments": ("journals", ("Despliegue", "Estado", "Clientes", "Eventos"), "journals"),
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
            self.query_one("#page-action", Button).label = "Verificar imagen seleccionada"
        elif page_id == "operation-log":
            self._operation_history = rows
            for item in rows:
                events = item.get("events") or []
                latest = events[-1] if events else {}
                progress = next((event.get("details") or {} for event in reversed(events) if event.get("state") == "progress"), {})
                operation_id = str(item.get("operation_id") or "—")
                details = latest.get("details") or {}
                details_text = details.get("error") or details.get("reason") or (
                    "El destino puede estar parcialmente escrito"
                    if details.get("destination_may_be_partial") else "—"
                )
                table.add_row(
                    operation_id, str(item.get("action") or "—"), str(item.get("state") or "unknown"),
                    str(latest.get("timestamp") or "—"),
                    f"{progress.get('bytes_done', 0)} / {progress.get('bytes_total', '—')} bytes",
                    str(details_text), key=operation_id,
                )
            self.query_one("#page-action", Button).display = bool(rows)
            self.query_one("#page-action", Button).label = "Solicitar cancelación"
            self.query_one("#page-confirmation", Input).display = bool(rows)
        elif page_id == "deployments":
            for item in rows:
                job_id = str(item.get("job_id") or "—")
                clients = item.get("clients") or {}
                table.add_row(
                    job_id, str(item.get("job_state") or "—"),
                    ", ".join(f"{mac}: {state}" for mac, state in clients.items()) or "—",
                    str(item.get("event_count") or 0), key=job_id,
                )
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
        elif page_id == "remote-jobs":
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
        inspection_errors = response.get("inspection_errors") or []
        if inspection_errors:
            identifiers = ", ".join(
                str(item.get("operation_id") or "desconocido")
                for item in inspection_errors[:5]
            )
            remainder = len(inspection_errors) - min(len(inspection_errors), 5)
            suffix = f" y {remainder} más" if remainder else ""
            message.update(
                f"Registros legibles: {len(rows)}. ATENCIÓN: {len(inspection_errors)} "
                f"operación(es) requieren inspección manual; no se han ocultado: "
                f"{identifiers}{suffix}. No reanudes ni repitas esas operaciones."
            )
        else:
            message.update(f"Registros: {len(rows)}")

    async def load_repositories_page(self) -> None:
        table = self.query_one("#page-table", DataTable)
        table.clear(columns=True)
        message = self.query_one("#page-message", Static)
        await self.refresh_repositories()
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

    async def refresh_repositories(self) -> None:
        try:
            remote = await call_feclora("remote_repositories")
            s3 = await call_feclora("s3_repositories")
            credentials = await call_feclora("systemd_credentials")
        except TUIAPIError as exc:
            self.query_one("#operation-result", Static).update(f"No se pudieron cargar los repositorios: {exc}")
            return
        self._repositories = remote.get("repositories") or []
        self._s3_repositories = s3.get("repositories") or []
        self._credentials = credentials.get("credentials") or []
        options = [("Repositorio local", "")]
        options.extend(
            (f"{item.get('id')} · {item.get('provider')} · {'montado' if item.get('mounted') else 'sin montar'}",
             item["id"])
            for item in self._repositories
            if item.get("id") and item.get("mounted") and item.get("verified")
        )
        options.extend(
            (f"{item.get('id')} · S3", item["id"])
            for item in self._s3_repositories if item.get("id")
        )
        repository_select = self.query_one("#repository-select", Select)
        current_value = repository_select.value
        selected = current_value if isinstance(current_value, str) else ""
        repository_select.set_options(options)
        if selected and any(value == selected for _, value in options):
            repository_select.value = selected
        else:
            repository_select.value = ""
        self._repository_selection_value = selected if selected and any(value == selected for _, value in options) else ""
        management_options = [("Selecciona repositorio…", "")]
        management_options.extend(
            (f"{item.get('id')} · {item.get('provider')}", f"remote:{item['id']}")
            for item in self._repositories if item.get("id")
        )
        management_options.extend(
            (f"{item.get('id')} · S3", f"s3:{item['id']}")
            for item in self._s3_repositories if item.get("id")
        )
        management_select = self.query_one("#repository-management-select", Select)
        management_value = management_select.value
        management_value = management_value if isinstance(management_value, str) else ""
        management_select.set_options(management_options)
        management_select.value = management_value if any(value == management_value for _, value in management_options) else ""
        for widget_id, credential_kind, label in (
            ("repository-identity", "ssh-key", "Selecciona clave SSH…"),
            ("repository-known-hosts", "known-hosts", "Selecciona known_hosts…"),
            ("repository-credentials", "smb", "Selecciona credencial SMB…"),
            ("s3-credential", "s3", "Selecciona credencial S3…"),
        ):
            select = self.query_one(f"#{widget_id}", Select)
            current = select.value
            current = current if isinstance(current, str) else ""
            credential_options = [(label, "")]
            credential_options.extend(
                (str(item.get("id")), str(item.get("path") if widget_id != "s3-credential" else item.get("id")))
                for item in self._credentials if item.get("kind") == credential_kind and item.get("id")
            )
            select.set_options(credential_options)
            select.value = current if any(value == current for _, value in credential_options) else ""
        credential_select = self.query_one("#credential-select", Select)
        credential_options = [("Selecciona una credencial…", "")]
        credential_options.extend(
            (f"{item.get('id')} · {item.get('kind')}", f"{item.get('kind')}:{item.get('id')}")
            for item in self._credentials if item.get("id") and item.get("kind")
        )
        current_credential = credential_select.value
        current_credential = current_credential if isinstance(current_credential, str) else ""
        credential_select.set_options(credential_options)
        credential_select.value = current_credential if any(value == current_credential for _, value in credential_options) else ""
        p2v_source = self.query_one("#p2v-source-repository", Select)
        p2v_source.set_options(
            [("Selecciona S3 de origen…", "")] +
            [(f"{item.get('id')} · {item.get('bucket')}/{item.get('prefix')}", item["id"])
             for item in self._s3_repositories if item.get("id")]
        )
        p2v_destination = self.query_one("#p2v-destination-repository", Select)
        p2v_destination.set_options(
            [("Repositorio local", "")] +
            [(f"{item.get('id')} · {item.get('provider')}", item["id"])
             for item in self._repositories
             if item.get("id") and item.get("mounted") and item.get("verified") and not item.get("read_only")]
        )
        self._update_repository_fields()

    def _update_repository_fields(self) -> None:
        provider_select = self.query_one("#repository-provider", Select)
        provider = provider_select.value if isinstance(provider_select.value, str) else "sshfs"
        self.query_one("#repository-username", Input).display = provider in {"sshfs", "smb"}
        self.query_one("#repository-identity", Select).display = provider == "sshfs"
        self.query_one("#repository-known-hosts", Select).display = provider == "sshfs"
        self.query_one("#repository-credentials", Select).display = provider == "smb"

    def _update_pxe_fields(self) -> None:
        isolated = self.query_one("#pxe-mode", Select).value == "isolated"
        for widget_id in (
            "pxe-pool-start", "pxe-pool-end", "pxe-gateway",
            "pxe-dns", "pxe-authoritative",
        ):
            self.query_one(f"#{widget_id}").display = isolated

    async def bootstrap_server(self) -> None:
        binding = self.query_one("#server-interface", Select).value
        selected = next((item for item in self._network_interfaces if item.get("binding") == binding), None)
        if not selected:
            self.query_one("#server-result", Static).update("Selecciona una dirección IPv4 local.")
            return
        try:
            result = await call_feclora("bootstrap_server", {
                "interface": selected["interface"],
                "address": selected["address"],
                "prefix_length": selected["prefix_length"],
            })
        except TUIAPIError as exc:
            self.query_one("#server-result", Static).update(f"No se pudo preparar el servidor: {exc}")
            return
        self.query_one("#server-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))
        await self.load_system_page("server")

    async def renew_server_certificate(self) -> None:
        confirmation = self.query_one("#server-renew-confirmation", Input).value
        if confirmation != "RENEW SERVER CERTIFICATE":
            self.query_one("#server-result", Static).update("Escribe exactamente «RENEW SERVER CERTIFICATE».")
            return
        try:
            result = await call_feclora("renew_server_certificate", {"confirmation": confirmation})
        except TUIAPIError as exc:
            self.query_one("#server-result", Static).update(f"No se pudo renovar el certificado: {exc}")
            return
        self.query_one("#server-renew-confirmation", Input).value = ""
        self.query_one("#server-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))
        await self.load_system_page("server")

    async def rotate_server_keypair(self) -> None:
        confirmation = self.query_one("#server-rotate-confirmation", Input).value
        if confirmation != "ROTATE SERVER TLS KEYPAIR":
            self.query_one("#server-result", Static).update("Escribe exactamente «ROTATE SERVER TLS KEYPAIR».")
            return
        try:
            result = await call_feclora("rotate_server_keypair", {"confirmation": confirmation})
        except TUIAPIError as exc:
            self.query_one("#server-result", Static).update(f"No se pudo rotar la clave TLS: {exc}")
            return
        self.query_one("#server-rotate-confirmation", Input).value = ""
        self.query_one("#server-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))
        await self.load_system_page("server")

    async def export_server_age_recipients(self) -> None:
        directory = self.query_one("#server-age-directory", Input).value.strip()
        if not directory:
            self.query_one("#server-result", Static).update("Indica el directorio de exportación protegido.")
            return
        try:
            result = await call_feclora("export_server_age_recipients", {"export_directory": directory})
        except TUIAPIError as exc:
            self.query_one("#server-result", Static).update(f"No se pudieron exportar los destinatarios: {exc}")
            return
        self.query_one("#server-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))

    async def refresh_client_age_recipients(self) -> None:
        path = self.query_one("#client-age-path", Input).value.strip()
        if not path:
            self.query_one("#server-result", Static).update("Indica la ruta del inventario de destinatarios del cliente.")
            return
        try:
            result = await call_feclora("refresh_client_age_recipients", {"inventory_path": path})
        except TUIAPIError as exc:
            self.query_one("#server-result", Static).update(f"No se pudo actualizar el inventario age: {exc}")
            return
        self.query_one("#server-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))

    async def validate_pxe_profile(self) -> None:
        binding = self.query_one("#server-interface", Select).value
        selected = next((item for item in self._network_interfaces if item.get("binding") == binding), None)
        if not selected:
            self.query_one("#pxe-result", Static).update("Selecciona la interfaz y dirección IPv4 del servidor.")
            return
        mode = str(self.query_one("#pxe-mode", Select).value)
        try:
            port = int(self.query_one("#pxe-port", Input).value)
            max_clients_text = self.query_one("#pxe-max-clients", Input).value.strip()
            max_duration_text = self.query_one("#pxe-max-duration", Input).value.strip()
            profile: dict[str, Any] = {
                "interface": selected["interface"],
                "address": selected["address"],
                "prefix_length": selected["prefix_length"],
                "mode": mode,
                "pool_start": self.query_one("#pxe-pool-start", Input).value.strip() or None if mode == "isolated" else None,
                "pool_end": self.query_one("#pxe-pool-end", Input).value.strip() or None if mode == "isolated" else None,
                "lease_time": self.query_one("#pxe-lease", Input).value.strip(),
                "gateway": self.query_one("#pxe-gateway", Input).value.strip() or None if mode == "isolated" else None,
                "dns_server": self.query_one("#pxe-dns", Input).value.strip() or None if mode == "isolated" else None,
                "http_port": port,
                "authoritative_confirmed": (
                    str(self.query_one("#pxe-authoritative", Select).value) == "true"
                    if mode == "isolated" else False
                ),
                "max_clients": int(max_clients_text) if max_clients_text else None,
                "max_duration_seconds": int(max_duration_text) if max_duration_text else None,
            }
        except ValueError:
            self.query_one("#pxe-result", Static).update("Puerto, límite de clientes y duración deben ser números enteros.")
            return
        try:
            result = await call_feclora("validate_pxe_profile", profile)
        except TUIAPIError as exc:
            self._pxe_profile = None
            self.query_one("#pxe-start", Button).disabled = True
            self.query_one("#pxe-result", Static).update(f"El perfil PXE no pasó la validación: {exc}")
            return
        self._pxe_profile = profile
        self.query_one("#pxe-start", Button).disabled = False
        self.query_one("#pxe-result", Static).update(
            str(result.get("message") or json.dumps(result, ensure_ascii=False, indent=2))
        )

    async def start_pxe_services(self) -> None:
        if self._pxe_profile is None:
            self.query_one("#pxe-result", Static).update("Valida un perfil PXE antes de iniciar servicios.")
            return
        try:
            result = await call_feclora("start_pxe_services", self._pxe_profile)
        except TUIAPIError as exc:
            self.query_one("#pxe-result", Static).update(f"No se pudieron iniciar los servicios PXE: {exc}")
            return
        self.query_one("#pxe-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))
        await self.load_system_page("server")

    async def stop_pxe_services(self) -> None:
        try:
            result = await call_feclora("stop_pxe_services")
        except TUIAPIError as exc:
            self.query_one("#pxe-result", Static).update(f"No se pudieron detener los servicios PXE: {exc}")
            return
        self.query_one("#pxe-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))
        await self.load_system_page("server")

    async def publish_pxe_answer(self) -> None:
        source = str(self.query_one("#pxe-answer-source", Select).value)
        job_id = self.query_one("#pxe-answer-job-id", Input).value.strip()
        path_or_url = self.query_one("#pxe-answer-path", Input).value.strip()
        request: dict[str, Any] = {"source": source}
        try:
            if source == "upload":
                if not path_or_url:
                    raise TUIAPIError("Indica la ruta local del archivo JSON.")
                payload = Path(path_or_url).expanduser().read_bytes()
                if not 1 <= len(payload) <= 64 * 1024:
                    raise TUIAPIError("El archivo debe tener entre 1 byte y 64 KiB.")
                if not job_id:
                    try:
                        document = json.loads(payload)
                        if isinstance(document, dict):
                            job_id = document.get("job_id") or ""
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                if not job_id:
                    job_id = str(uuid.uuid4())
                request["answer_base64"] = base64.b64encode(payload).decode("ascii")
            elif source == "url":
                if not path_or_url or not job_id:
                    raise TUIAPIError("Indica la URL y el UUID del trabajo contenido en la respuesta.")
                request["url"] = path_or_url
            else:
                repository_id = self.query_one("#pxe-answer-repository", Select).value
                source_path = self.query_one("#pxe-answer-source-path", Input).value.strip()
                if not repository_id or not job_id or not source_path:
                    raise TUIAPIError("Selecciona repositorio e indica el UUID y la ruta relativa del archivo.")
                request.update(repository_id=repository_id, source_path=source_path)
            request["job_id"] = job_id
            result = await call_feclora("publish_pxe_answer", request)
        except (TUIAPIError, OSError) as exc:
            self.query_one("#pxe-answer-result", Static).update(f"No se pudo publicar la respuesta: {exc}")
            return
        self._pxe_published_answer = result
        self.query_one("#pxe-answer-revoke-id", Input).value = str(result.get("job_id") or job_id)
        self.query_one("#pxe-answer-result", Static).update(
            str(result.get("message") or json.dumps(result, ensure_ascii=False, indent=2))
        )
        await self.refresh_pxe_passphrase_status()

    async def revoke_pxe_answer(self) -> None:
        job_id = self.query_one("#pxe-answer-revoke-id", Input).value.strip()
        if not job_id:
            self.query_one("#pxe-answer-result", Static).update("Indica el UUID de la respuesta que quieres revocar.")
            return
        try:
            result = await call_feclora("revoke_pxe_answer", {"job_id": job_id})
        except TUIAPIError as exc:
            self.query_one("#pxe-answer-result", Static).update(f"No se pudo revocar la respuesta: {exc}")
            return
        self._pxe_published_answer = None
        self.query_one("#pxe-answer-result", Static).update(str(result.get("message") or json.dumps(result, ensure_ascii=False)))

    async def refresh_pxe_passphrase_status(self) -> None:
        try:
            status = await call_feclora("pxe_age_passphrase_status")
        except TUIAPIError as exc:
            self.query_one("#pxe-passphrase-status", Static).update(f"No se pudo consultar la frase PXE: {exc}")
            return
        waiting = bool(status.get("waiting"))
        self.query_one("#pxe-passphrase-status", Static).update(
            "Hay una frase age pendiente." if waiting else "No hay frases age pendientes."
        )
        self.query_one("#pxe-passphrase", Input).display = waiting
        self.query_one("#pxe-passphrase-submit", Button).display = waiting

    async def submit_pxe_passphrase(self) -> None:
        passphrase = self.query_one("#pxe-passphrase", Input).value
        if not passphrase:
            self.query_one("#pxe-passphrase-status", Static).update("Introduce la frase age pendiente.")
            return
        try:
            result = await call_feclora("provide_pxe_age_passphrase", {"passphrase": passphrase})
        except TUIAPIError as exc:
            self.query_one("#pxe-passphrase-status", Static).update(f"No se pudo enviar la frase: {exc}")
            return
        self.query_one("#pxe-passphrase", Input).value = ""
        self.query_one("#pxe-passphrase-status", Static).update(
            str(result.get("message") or "Frase enviada por el canal de un solo uso.")
        )
        await self.refresh_pxe_passphrase_status()

    async def load_system_page(self, page_id: str) -> None:
        table = self.query_one("#page-table", DataTable)
        table.clear(columns=True)
        message = self.query_one("#page-message", Static)
        try:
            if page_id == "server":
                status, pxe, interfaces = await asyncio.gather(
                    call_feclora("status"),
                    call_feclora("pxe_service_status"),
                    call_feclora("network_interfaces"),
                )
                self._network_interfaces = interfaces.get("interfaces") or []
                await self.refresh_repositories()
                await self.refresh_pxe_passphrase_status()
                self.query_one("#server-interface", Select).set_options(
                    [("Selecciona interfaz/dirección activa…", "")] +
                    [(f"{item.get('interface')} · {item.get('address')}/{item.get('prefix_length')}",
                      str(item.get("binding")))
                     for item in self._network_interfaces if item.get("binding")]
                )
                remote = [
                    (f"{item.get('id')} · {item.get('provider')}", item["id"])
                    for item in self._repositories if item.get("id")
                ]
                s3 = [
                    (f"{item.get('id')} · S3", item["id"])
                    for item in self._s3_repositories if item.get("id")
                ]
                self.query_one("#pxe-answer-repository", Select).set_options(
                    [("Selecciona repositorio…", "")] + remote + s3
                )
            else:
                status = await call_feclora("status")
                pxe = {}
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
            self.query_one("#pxe-start", Button).disabled = self._pxe_profile is None
        for index, (name, value) in enumerate(components):
            table.add_row(str(name), str(value or "—"), key=f"{page_id}:{index}")
        message.update("Estado actualizado.")

    async def run_page_action(self) -> None:
        if not self._selected_page_row:
            return
        if self._current_page == "operation-log":
            expected = f"CANCEL {self._selected_page_row}"
            confirmation = self.query_one("#page-confirmation", Input).value
            if confirmation != expected:
                self.query_one("#page-action-result", Static).update(
                    f"Escribe exactamente «{expected}» para solicitar la cancelación."
                )
                return
            try:
                result = await call_feclora(
                    "cancel_local_operation", {"operation_id": self._selected_page_row},
                )
            except TUIAPIError as exc:
                self.query_one("#page-action-result", Static).update(f"No se pudo cancelar: {exc}")
                return
            self.query_one("#page-action-result", Static).update(
                f"Resultado de cancelación: {json.dumps(result, ensure_ascii=False)}"
            )
            self.query_one("#page-confirmation", Input).value = ""
            await self.load_page("operation-log")
            return
        if self._current_page != "images":
            return
        repository_id = self._current_image_repository()
        params = {"image_id": self._selected_page_row}
        if repository_id:
            params["repository_id"] = repository_id
        try:
            result = await call_feclora("verify_image", params)
        except TUIAPIError as exc:
            self.query_one("#page-action-result", Static).update(f"Error al verificar la imagen: {exc}")
        else:
            self.query_one("#page-action-result", Static).update(
                f"Verificación: {json.dumps(result, ensure_ascii=False)}"
            )

    async def save_remote_repository(self) -> None:
        repository_id = self.query_one("#repository-id", Input).value.strip()
        provider = str(self.query_one("#repository-provider", Select).value)
        host = self.query_one("#repository-host", Input).value.strip()
        remote_path = self.query_one("#repository-path", Input).value.strip()
        port_text = self.query_one("#repository-port", Input).value.strip()
        try:
            port = int(port_text) if port_text else None
        except ValueError as exc:
            self.query_one("#page-action-result", Static).update("El puerto debe ser un número.")
            return
        if not repository_id or not host or not remote_path:
            self.query_one("#page-action-result", Static).update("ID, servidor y ruta son obligatorios.")
            return
        params = {
            "id": repository_id,
            "provider": provider,
            "host": host,
            "remote_path": remote_path,
            "username": self.query_one("#repository-username", Input).value.strip() or None
            if provider in {"sshfs", "smb"} else None,
            "credential_file": str(self.query_one("#repository-credentials", Select).value or "")
            if provider == "smb" else None,
            "identity_file": str(self.query_one("#repository-identity", Select).value or "")
            if provider == "sshfs" else None,
            "known_hosts_file": str(self.query_one("#repository-known-hosts", Select).value or "")
            if provider == "sshfs" else None,
            "port": port if provider in {"sshfs", "smb"} else None,
            "read_only": str(self.query_one("#repository-read-only", Select).value) == "true",
        }
        action = "update_remote_repository" if any(item.get("id") == repository_id for item in self._repositories) else "add_remote_repository"
        await self._call_repository_api(action, params, f"Definición {repository_id} guardada; no se inició ningún montaje.")

    async def run_repository_action(self) -> None:
        selection = str(self.query_one("#repository-management-select", Select).value or "")
        action = str(self.query_one("#repository-management-action", Select).value)
        if ":" not in selection:
            self.query_one("#page-action-result", Static).update("Selecciona un repositorio.")
            return
        kind, repository_id = selection.split(":", 1)
        if action == "edit":
            repository = next((item for item in self._repositories if item.get("id") == repository_id), None)
            if not repository:
                self.query_one("#page-action-result", Static).update("Solo se pueden editar definiciones de repositorios de archivos.")
                return
            if repository.get("mount_state") != "unmounted":
                self.query_one("#page-action-result", Static).update("Desmonta el repositorio y confirma que está sin montar antes de editar.")
                return
            self.query_one("#repository-id", Input).value = repository_id
            self.query_one("#repository-id", Input).read_only = True
            self.query_one("#repository-provider", Select).value = repository.get("provider", "sshfs")
            self.query_one("#repository-host", Input).value = repository.get("host", "")
            self.query_one("#repository-path", Input).value = repository.get("remote_path", "")
            self.query_one("#repository-username", Input).value = repository.get("username") or ""
            self.query_one("#repository-identity", Select).value = repository.get("identity_file") or ""
            self.query_one("#repository-known-hosts", Select).value = repository.get("known_hosts_file") or ""
            self.query_one("#repository-credentials", Select).value = repository.get("credential_file") or ""
            self.query_one("#repository-port", Input).value = str(repository.get("port") or "")
            self.query_one("#repository-read-only", Select).value = "true" if repository.get("read_only") else "false"
            self._update_repository_fields()
            self.query_one("#page-action-result", Static).update(f"Editando {repository_id}; guarda la definición para aplicar los cambios.")
            return
        if action in {"remove_remote_repository", "remove_s3_repository"}:
            expected = f"REMOVE {repository_id}"
            confirmation = self.query_one("#repository-removal-confirmation", Input).value
            if confirmation != expected:
                self.query_one("#page-action-result", Static).update(f"Para eliminar, escribe exactamente «{expected}».")
                return
        if kind == "s3" and action not in {"check_s3_repository", "remove_s3_repository"}:
            self.query_one("#page-action-result", Static).update("La acción seleccionada no es compatible con un repositorio S3.")
            return
        if kind != "s3" and action in {"check_s3_repository", "remove_s3_repository"}:
            self.query_one("#page-action-result", Static).update("La acción S3 requiere seleccionar un repositorio S3.")
            return
        if action in {"mount_remote_repository", "remove_remote_repository"}:
            repository = next((item for item in self._repositories if item.get("id") == repository_id), {})
            if repository.get("mount_state") != "unmounted":
                self.query_one("#page-action-result", Static).update("La acción requiere un estado de montaje confirmado como desmontado.")
                return
        if action == "unmount_remote_repository":
            repository = next((item for item in self._repositories if item.get("id") == repository_id), {})
            if repository.get("mount_state") != "identity_verified":
                self.query_one("#page-action-result", Static).update("Solo se desmontan repositorios cuya identidad de montaje se verificó.")
                return
        await self._call_repository_api(action, {"id": repository_id}, f"Acción {action} completada para {repository_id}.")
        self.query_one("#repository-removal-confirmation", Input).value = ""

    async def import_credential(self) -> None:
        params = {
            "id": self.query_one("#credential-id", Input).value.strip(),
            "kind": str(self.query_one("#credential-kind", Select).value),
            "source_file": self.query_one("#credential-source", Input).value.strip(),
            "replace": str(self.query_one("#credential-replace", Select).value) == "true",
        }
        if not params["id"] or not params["source_file"]:
            self.query_one("#page-action-result", Static).update("Indica el ID y la ruta protegida del archivo fuente.")
            return
        await self._call_repository_api(
            "put_systemd_credential", params,
            "Credencial cifrada importada; el archivo fuente no se eliminó.",
        )

    async def remove_credential(self) -> None:
        selection = str(self.query_one("#credential-select", Select).value or "")
        if ":" not in selection:
            self.query_one("#page-action-result", Static).update("Selecciona una credencial.")
            return
        kind, credential_id = selection.split(":", 1)
        if self.query_one("#credential-removal-confirmation", Input).value != f"REMOVE {credential_id}":
            self.query_one("#page-action-result", Static).update(f"Para eliminar, escribe exactamente «REMOVE {credential_id}».")
            return
        refs = {
            item.get("credential_file") for item in self._repositories
        } | {
            ref for item in self._repositories for ref in item.get("credential_refs", [])
        } | {
            ref for item in self._s3_repositories for ref in item.get("credential_refs", [])
        }
        credential = next((item for item in self._credentials if item.get("id") == credential_id and item.get("kind") == kind), None)
        if not credential:
            self.query_one("#page-action-result", Static).update("La credencial ya no está disponible.")
            return
        if credential.get("path") in refs:
            self.query_one("#page-action-result", Static).update("No se puede eliminar: la credencial está referenciada por un repositorio.")
            return
        await self._call_repository_api(
            "remove_systemd_credential", {"id": credential_id, "kind": kind},
            f"Credencial {credential_id} eliminada.",
        )
        self.query_one("#credential-removal-confirmation", Input).value = ""

    async def save_s3_repository(self) -> None:
        params = {
            "id": self.query_one("#s3-id", Input).value.strip(),
            "endpoint_url": self.query_one("#s3-endpoint", Input).value.strip() or None,
            "region": self.query_one("#s3-region", Input).value.strip(),
            "bucket": self.query_one("#s3-bucket", Input).value.strip(),
            "prefix": self.query_one("#s3-prefix", Input).value.strip(),
            "credential_id": str(self.query_one("#s3-credential", Select).value or ""),
            "read_only": str(self.query_one("#s3-read-only", Select).value) == "true",
        }
        if not all(params[key] for key in ("id", "region", "bucket", "credential_id")):
            self.query_one("#page-action-result", Static).update("ID, región, bucket y credencial S3 son obligatorios.")
            return
        await self._call_repository_api(
            "add_s3_repository", params, f"Repositorio S3 {params['id']} guardado.",
        )

    async def export_p2v(self) -> None:
        image_id = self.query_one("#p2v-image-id", Input).value.strip()
        source_id = str(self.query_one("#p2v-source-repository", Select).value or "")
        destination_id = str(self.query_one("#p2v-destination-repository", Select).value or "")
        if not image_id or not source_id:
            self.query_one("#page-action-result", Static).update("Selecciona el repositorio S3 e indica el identificador de imagen.")
            return
        params: dict[str, Any] = {"image_id": image_id, "source_repository_id": source_id}
        if destination_id:
            params["destination_repository_id"] = destination_id
        try:
            accepted = await call_feclora("export_p2v_s3", params)
        except TUIAPIError as exc:
            self.query_one("#page-action-result", Static).update(f"No se pudo iniciar la exportación: {exc}")
            return
        operation_id = accepted.get("operation_id")
        if not operation_id:
            self.query_one("#page-action-result", Static).update("El backend no devolvió un identificador de operación.")
            return
        self.query_one("#page-action-result", Static).update(f"Exportación P2V {operation_id} aceptada.")
        await self._wait_for_operation(operation_id, "#page-action-result")

    async def _call_repository_api(self, action: str, params: dict[str, Any], success: str) -> None:
        try:
            await call_feclora(action, params)
        except TUIAPIError as exc:
            self.query_one("#page-action-result", Static).update(f"Error en {action}: {exc}")
            return
        self.query_one("#page-action-result", Static).update(success)
        await self.load_repositories_page()

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
        is_disk = operation.endswith("_disk") or operation == "capture_p2v"
        is_logical_volume = operation.endswith("_logical_volume")
        is_stratis_filesystem = operation.endswith("_stratis_filesystem")
        is_recovery_iso = operation == "build_recovery_iso"
        is_bundle = operation == "build_deployment_bundle"
        source_label = self.query_one("#source-label", Static)
        target_label = self.query_one("#target-label", Static)
        source_select = self.query_one("#source-device", Select)
        target_select = self.query_one("#target-device", Select)
        image_select = self.query_one("#existing-image", Select)
        self.query_one("#source-label", Static).display = is_capture or is_clone or operation == "restore_proportional_disk"
        source_select.display = source_label.display
        target_label.display = is_restore or is_clone
        target_select.display = target_label.display
        self.query_one("#new-image-label", Static).display = is_capture
        self.query_one("#new-image-id", Input).display = is_capture
        self.query_one("#existing-image-label", Static).display = is_restore or is_recovery_iso or is_bundle
        image_select.display = is_restore or is_recovery_iso or is_bundle
        self.query_one("#format-label", Static).display = operation == "capture_disk"
        self.query_one("#image-format", Select).display = operation == "capture_disk"
        self.query_one("#compression-label", Static).display = is_capture and operation != "capture_p2v"
        self.query_one("#compression", Select).display = is_capture and operation != "capture_p2v"
        self.query_one("#encrypt-toggle", Button).display = is_capture and operation != "capture_p2v" and not (operation == "capture_disk" and str(self.query_one("#image-format", Select).value) == "qcow2")
        self.query_one("#encrypt-passphrase-toggle", Button).display = operation == "capture_disk" and str(self.query_one("#image-format", Select).value) != "qcow2"
        self.query_one("#capture-passphrase", Input).display = self.query_one("#encrypt-passphrase-toggle", Button).display and self.query_one("#encrypt-passphrase-toggle", Button).variant == "success"
        self.query_one("#repository-label", Static).display = True
        self.query_one("#repository-select", Select).display = True
        self.query_one("#base-iso-label", Static).display = is_recovery_iso or is_bundle
        self.query_one("#base-iso", Input).display = is_recovery_iso or is_bundle
        self.query_one("#target-wwn-label", Static).display = is_recovery_iso
        self.query_one("#target-wwn", Input).display = is_recovery_iso
        self.query_one("#target-serial-label", Static).display = is_recovery_iso
        self.query_one("#target-serial", Input).display = is_recovery_iso
        self.query_one("#bundle-name-label", Static).display = is_bundle
        self.query_one("#bundle-name", Input).display = is_bundle
        self.query_one("#deployment-job-label", Static).display = is_bundle
        self.query_one("#deployment-job", TextArea).display = is_bundle
        self.query_one("#confirmation", Input).display = is_restore or is_clone or is_recovery_iso
        self.query_one("#confirmation-prompt", Static).display = is_restore or is_clone or is_recovery_iso
        if is_logical_volume:
            source_devices = self._logical_volumes
        elif is_stratis_filesystem:
            source_devices = [
                item for item in self._devices
                if item.get("type") == "dm" and str(item.get("filesystem") or "").lower() == "xfs"
            ]
        else:
            source_devices = [
                item for item in self._devices
                if item.get("type") == ("disk" if is_disk or operation == "restore_proportional_disk" else "part")
            ]
        if is_logical_volume:
            target_devices = self._logical_volumes
        elif is_stratis_filesystem:
            target_devices = [
                item for item in self._devices
                if item.get("type") == "dm" and str(item.get("filesystem") or "").lower() == "xfs"
            ]
        else:
            target_devices = [
                item for item in self._devices if item.get("type") == ("disk" if is_disk else "part")
            ]
        if operation in {"capture_disk", "capture_p2v", "capture_partition", "capture_logical_volume", "capture_stratis_filesystem", "clone_disk", "clone_partition", "restore_proportional_disk"}:
            self._set_device_options(source_select, source_devices)
        else:
            self._set_device_options(source_select, [])
        if is_restore or is_clone:
            self._set_device_options(target_select, target_devices)
        else:
            self._set_device_options(target_select, [])
        image_type = "stratis_filesystem" if is_stratis_filesystem else "logical_volume" if is_logical_volume else "disk" if is_disk or is_recovery_iso or is_bundle else "partition"
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
        elif operation == "build_recovery_iso" and str(self.query_one("#existing-image", Select).value or ""):
            phrase = f"BUILD {self.query_one('#existing-image', Select).value}"
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
        capture_passphrase: str | None = None
        message.update("")
        try:
            if operation.startswith("capture_"):
                if not source or not new_image_id:
                    raise TUIAPIError("Selecciona el origen e indica un identificador de imagen.")
                repository_id = str(self.query_one("#repository-select", Select).value or "")
                params: dict[str, Any] = {"source": source, "image_id": new_image_id}
                if operation == "capture_p2v":
                    if repository_id:
                        params["repository_id"] = repository_id
                else:
                    params.update(
                        compression=str(self.query_one("#compression", Select).value),
                        encrypt=self.query_one("#encrypt-toggle", Button).variant == "success"
                        or self.query_one("#encrypt-passphrase-toggle", Button).variant == "success",
                    )
                    if repository_id:
                        params["repository_id"] = repository_id
                if operation == "capture_disk":
                    image_format = str(self.query_one("#image-format", Select).value)
                    params["image_format"] = image_format
                    if image_format == "qcow2":
                        params.update(compression="none", encrypt=False)
                    elif self.query_one("#encrypt-passphrase-toggle", Button).variant == "success":
                        params["encrypt_passphrase"] = True
                elif operation == "capture_partition":
                    params["partition_id"] = new_image_id
                if operation == "capture_disk" and self.query_one("#encrypt-passphrase-toggle", Button).variant == "success":
                    capture_passphrase = self.query_one("#capture-passphrase", Input).value
                    if not capture_passphrase:
                        raise TUIAPIError("Indica una frase secreta para cifrar la captura.")
                    params["encrypt_passphrase"] = True
            elif operation == "build_recovery_iso":
                image_id = str(self.query_one("#existing-image", Select).value or "")
                base_iso = self.query_one("#base-iso", Input).value.strip()
                repository_id = str(self.query_one("#repository-select", Select).value or "")
                if not image_id or not base_iso or not repository_id:
                    raise TUIAPIError("Indica la imagen, la ISO base y un repositorio remoto montado y escribible.")
                repository = next((item for item in self._repositories if item.get("id") == repository_id), None)
                if not repository or not repository.get("mounted") or not repository.get("verified") or repository.get("read_only"):
                    raise TUIAPIError("La ISO de recuperación necesita un repositorio de archivos montado, verificado y escribible.")
                params = {
                    "image_id": image_id,
                    "base_iso_path": base_iso,
                    "target_wwn": self.query_one("#target-wwn", Input).value.strip() or None,
                    "target_serial": self.query_one("#target-serial", Input).value.strip() or None,
                    "confirm_build": confirmation,
                    "repository_id": repository_id,
                }
            elif operation == "build_deployment_bundle":
                repository_id = str(self.query_one("#repository-select", Select).value or "")
                if not repository_id:
                    raise TUIAPIError("Selecciona un repositorio remoto montado y escribible.")
                repository = next((item for item in self._repositories if item.get("id") == repository_id), None)
                if not repository or not repository.get("mounted") or not repository.get("verified") or repository.get("read_only"):
                    raise TUIAPIError("El paquete de despliegue necesita un repositorio de archivos montado, verificado y escribible.")
                try:
                    deployment_job = json.loads(self.query_one("#deployment-job", TextArea).text)
                except json.JSONDecodeError as exc:
                    raise TUIAPIError(f"El JSON del DeploymentJob no es válido: {exc}") from exc
                params = {
                    "base_iso_path": self.query_one("#base-iso", Input).value.strip(),
                    "image_id": str(self.query_one("#existing-image", Select).value or ""),
                    "bundle_name": self.query_one("#bundle-name", Input).value.strip(),
                    "deployment_job": deployment_job,
                    "repository_id": repository_id,
                }
            elif operation.startswith("restore_"):
                if not image_id or not target:
                    raise TUIAPIError("Selecciona una imagen y un destino.")
                expected = f"ERASE {target}"
                if confirmation != expected:
                    raise TUIAPIError(f"Escribe exactamente «{expected}» para autorizar el destino.")
                params = {"image_id": image_id, "target": target, "confirmation": confirmation}
                repository_id = str(self.query_one("#repository-select", Select).value or "")
                if repository_id:
                    params["repository_id"] = repository_id
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
            if capture_passphrase:
                await call_feclora("provide_capture_passphrase", {
                    "operation_id": operation_id,
                    "passphrase": capture_passphrase,
                })
                self.query_one("#capture-passphrase", Input).value = ""
            progress_bar = self.query_one("#operation-progress", ProgressBar)
            progress_bar.display = True
            message.update(f"Operación {operation_id} aceptada. Consultando progreso…")
            await self._wait_for_operation(operation_id)
        except TUIAPIError as exc:
            message.update(f"Operación fallida: {exc}")
        finally:
            start_button.disabled = False

    async def _wait_for_operation(self, operation_id: str, message_selector: str = "#operation-result") -> None:
        message = self.query_one(message_selector, Static)
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
            if message_selector != "#page-message":
                self.query_one("#page-message", Static).update(
                    f"Operación {operation_id}: {state} · {done} bytes"
                )
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
                if self._current_page == "operations":
                    await self.refresh_inventory()
                    await self.refresh_images()
                elif self._current_page == "repositories":
                    await self.load_repositories_page()
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

    async def refresh_images(self, repository_id: str | None = None) -> None:
        if repository_id is None:
            selected = self.query_one("#repository-select", Select).value
            repository_id = selected if isinstance(selected, str) else ""
        try:
            response = (
                await call_feclora("repository_images", {"repository_id": repository_id})
                if repository_id else await call_feclora("images")
            )
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
