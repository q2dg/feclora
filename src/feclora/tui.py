"""Keyboard-first Textual interface for the Feclora Live appliance."""
from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Static

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
    .nav-button {
        width: 100%;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        ("ctrl+r", "refresh_data", "Actualizar"),
        ("q", "quit", "Salir"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._status: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="layout"):
            with Vertical(id="navigation"):
                yield Static("Feclora · navegación", id="navigation-title")
                for page_id, label in PAGES:
                    yield Button(label, id=f"nav-{page_id}", classes="nav-button")
            with Vertical(id="content"):
                yield Static("Inicio", id="page-title")
                yield Static("Cargando estado del sistema…", id="page-message")
                yield DataTable(id="inventory-table")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#inventory-table", DataTable)
        table.add_columns("Dispositivo", "Tipo", "Tamaño", "Modelo", "Sistema de archivos", "Montajes")
        table.display = False
        await self.refresh_data()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        page_id = (event.button.id or "").removeprefix("nav-")
        page = next((item for item in PAGES if item[0] == page_id), None)
        if page is None:
            return
        self.query_one("#page-title", Static).update(page[1])
        table = self.query_one("#inventory-table", DataTable)
        table.display = page_id == "inventory"
        if page_id == "overview":
            await self.refresh_data()
        elif page_id == "inventory":
            await self.refresh_inventory()
        else:
            self.query_one("#page-message", Static).update(
                "Esta pantalla forma parte de la migración progresiva a Textual."
            )

    async def action_refresh_data(self) -> None:
        await self.refresh_data()

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


def main() -> None:
    FecloraTUI().run()


if __name__ == "__main__":
    main()
