"""CustomTkinter frontend shell; operational pages are migrated incrementally.

This module is deliberately not the boot entry point yet. The Live image keeps
the proven Textual frontend until every operator workflow has a GUI equivalent.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import customtkinter as ctk

from feclora.gui_api import TkAPIClient, TUIAPIError
from feclora.ui_catalog import KEYBOARD_LAYOUTS, LANGUAGES, MESSAGES, PAGES, PAGE_MESSAGE_KEYS


class FecloraGUI(ctk.CTk):
    """Fullscreen, borderless operator shell for the CustomTkinter migration."""

    def __init__(self) -> None:
        super().__init__()
        self._language = self._load_language()
        self._keyboard_layout = "us"
        self._api = TkAPIClient(self)
        self._page_title: ctk.CTkLabel | None = None
        self._page_description: ctk.CTkLabel | None = None

        self.title("Feclora")
        self.configure(fg_color="#071a33")
        self.attributes("-fullscreen", True)
        self.overrideredirect(True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._ignore_window_close)
        for sequence in ("<Alt-F4>", "<Escape>", "<Control-q>", "<Control-Q>"):
            self.bind_all(sequence, self._block_window_shortcut)

        self._show_welcome()
        self.after_idle(self._report_boot_rendered)
        self._api.submit(
            "get_keyboard_layout",
            on_success=self._accept_startup_keyboard_layout,
            on_error=self._show_api_error,
        )

    @staticmethod
    def _language_path() -> Path:
        home = Path(os.environ.get("HOME", str(Path.home())))
        return home / ".config/feclora/language"

    @classmethod
    def _load_language(cls) -> str:
        try:
            language = cls._language_path().read_text(encoding="utf-8").strip()
        except (FileNotFoundError, UnicodeError, OSError):
            return "es"
        supported = {code for _label, code in LANGUAGES}
        return language if language in supported else "es"

    @classmethod
    def _save_language(cls, language: str) -> None:
        if language not in MESSAGES:
            raise ValueError("unsupported interface language")
        path = cls._language_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(language + "\n", encoding="utf-8")
        path.chmod(0o600)

    def _text(self, key: str) -> str:
        return MESSAGES.get(self._language, MESSAGES["es"]).get(
            key, MESSAGES["es"].get(key, key)
        )

    @staticmethod
    def _ignore_window_close() -> None:
        return None

    @staticmethod
    def _block_window_shortcut(_event: Any) -> str:
        return "break"

    def _report_boot_rendered(self) -> None:
        if Path("/dev/virtio-ports/org.feclora.boot-smoke").exists():
            ready = Path("/run/feclora-gui/ready")
            ready.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            ready.write_text("rendered\n", encoding="ascii")

    def _show_api_error(self, error: Exception) -> None:
        if hasattr(self, "_status_label"):
            self._status_label.configure(text=f"{self._text('apply_error')} {error}")

    def _accept_startup_keyboard_layout(self, result: dict[str, Any]) -> None:
        layout = result.get("layout")
        if layout in {value for _label, value in KEYBOARD_LAYOUTS}:
            self._keyboard_layout = layout
            if hasattr(self, "_keyboard_menu"):
                self._keyboard_menu.set(layout)

    def _clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def _show_welcome(self) -> None:
        self._clear()
        panel = ctk.CTkFrame(self, fg_color="#0b2b50", corner_radius=18)
        panel.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.76, relheight=0.78)

        ctk.CTkLabel(
            panel, text=self._text("first_title"),
            font=ctk.CTkFont(size=34, weight="bold"), text_color="#ffffff",
        ).pack(pady=(42, 10))
        ctk.CTkLabel(
            panel, text=self._text("tagline"),
            font=ctk.CTkFont(size=17), text_color="#c5d8ee",
            wraplength=900,
        ).pack(pady=(0, 32))

        ctk.CTkLabel(panel, text=self._text("language"), anchor="w").pack(
            fill="x", padx=90, pady=(8, 6)
        )
        self._language_menu = ctk.CTkOptionMenu(
            panel,
            values=[code for _label, code in LANGUAGES],
            command=self._change_language,
            width=360,
            height=42,
        )
        self._language_menu.set(self._language)
        self._language_menu.pack(pady=(0, 12))

        ctk.CTkLabel(panel, text=self._text("keyboard"), anchor="w").pack(
            fill="x", padx=90, pady=(8, 6)
        )
        self._keyboard_menu = ctk.CTkOptionMenu(
            panel,
            values=[value for _label, value in KEYBOARD_LAYOUTS],
            width=360,
            height=42,
        )
        self._keyboard_menu.set(self._keyboard_layout)
        self._keyboard_menu.pack(pady=(0, 12))

        self._status_label = ctk.CTkLabel(
            panel, text=self._text("language_scope"),
            text_color="#c5d8ee", wraplength=900,
        )
        self._status_label.pack(pady=(8, 20))

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(pady=12)
        ctk.CTkButton(
            actions, text=self._text("apply_keyboard"),
            command=self._apply_keyboard_layout, width=250, height=46,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            actions, text=self._text("continue"),
            command=self._continue_to_shell, width=220, height=46,
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            panel, text=self._text("terminal"),
            command=self._open_root_terminal, fg_color="#354b64",
            hover_color="#496582", width=250, height=42,
        ).pack(pady=(18, 28))

    def _change_language(self, language: str) -> None:
        if language not in MESSAGES:
            return
        self._language = language
        self._show_welcome()

    def _apply_keyboard_layout(self) -> None:
        layout = self._keyboard_menu.get()
        self._status_label.configure(text="Aplicando distribución del teclado…")
        self._api.submit(
            "set_keyboard_layout",
            {"layout": layout},
            on_success=lambda _result: self._status_label.configure(text=self._text("apply_ok")),
            on_error=self._show_api_error,
        )

    def _open_root_terminal(self) -> None:
        self._api.submit(
            "open_root_terminal",
            on_success=lambda _result: self._status_label.configure(
                text="Solicitud de terminal root enviada."
            ),
            on_error=self._show_api_error,
        )

    def _continue_to_shell(self) -> None:
        self._language = self._language_menu.get()
        try:
            self._save_language(self._language)
        except OSError as exc:
            self._status_label.configure(text=f"No se pudo guardar el idioma: {exc}")
            return
        self._show_navigation_shell()

    def _show_navigation_shell(self) -> None:
        self._clear()
        layout = ctk.CTkFrame(self, fg_color="#071a33", corner_radius=0)
        layout.pack(fill="both", expand=True)

        sidebar = ctk.CTkScrollableFrame(
            layout, width=300, fg_color="#0b2b50", corner_radius=0,
        )
        sidebar.pack(side="left", fill="y", padx=(0, 2), pady=0)
        ctk.CTkLabel(
            sidebar, text="FECLORA", font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(padx=20, pady=(24, 22))

        content = ctk.CTkFrame(layout, fg_color="#0b2442", corner_radius=0)
        content.pack(side="left", fill="both", expand=True, padx=0, pady=0)
        self._page_title = ctk.CTkLabel(
            content, text=self._text("overview"),
            font=ctk.CTkFont(size=30, weight="bold"), anchor="w",
        )
        self._page_title.pack(fill="x", padx=36, pady=(34, 16))
        self._page_description = ctk.CTkLabel(
            content,
            text="La migración de las pantallas operativas está en curso. "
                 "La interfaz Textual sigue siendo la versión de producción.",
            font=ctk.CTkFont(size=17), anchor="nw", justify="left",
            wraplength=1100,
        )
        self._page_description.pack(fill="both", expand=True, padx=36, pady=16)

        for page_id, _label in PAGES:
            ctk.CTkButton(
                sidebar,
                text=self._text(PAGE_MESSAGE_KEYS[page_id]),
                anchor="w",
                fg_color="transparent",
                hover_color="#17436d",
                command=lambda selected=page_id: self._select_placeholder_page(selected),
            ).pack(fill="x", padx=12, pady=3)

    def _select_placeholder_page(self, page_id: str) -> None:
        if self._page_title is not None:
            self._page_title.configure(text=self._text(PAGE_MESSAGE_KEYS[page_id]))
        if self._page_description is not None:
            self._page_description.configure(
                text="Esta pantalla todavía no está migrada. "
                     "El arranque de producción permanece en Textual hasta "
                     "completar y validar todos los flujos operativos."
            )

    def destroy(self) -> None:
        if hasattr(self, "_api"):
            self._api.close()
        super().destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = FecloraGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
