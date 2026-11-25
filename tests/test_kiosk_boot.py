from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KioskBootConfigurationTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_gtk_kiosk_owns_tty1_with_native_wayland_and_logind(self):
        service = self.read("src/feclora/data/feclora-gtk.service")
        self.assertIn("User=feclora", service)
        self.assertIn("PAMName=login", service)
        self.assertIn("Wants=dbus.socket systemd-logind.service", service)
        self.assertIn("TTYPath=/dev/tty1", service)
        self.assertIn(
            "ExecStart=/usr/bin/cage -x -s -- /usr/bin/python3 -m feclora.gui_gtk",
            service,
        )
        self.assertIn("RuntimeDirectory=feclora-gtk", service)
        self.assertIn("ExecStartPost=+/usr/libexec/feclora/feclora-gtk-ready", service)
        self.assertIn("Conflicts=getty@tty1.service feclora-tui.service", service)

    def test_textual_is_installed_as_mutually_exclusive_fallback_not_enabled(self):
        tui = self.read("src/feclora/data/feclora-tui.service")
        gtk = self.read("src/feclora/data/feclora-gtk.service")
        kickstart = self.read("kickstart/feclora-live.ks")
        self.assertIn("Conflicts=getty@tty1.service feclora-gtk.service", tui)
        self.assertIn('enable feclora-gtk.service', kickstart)
        self.assertNotIn('enable feclora-tui.service', kickstart)
        self.assertIn('feclora-tui.service', kickstart)

    def test_kickstart_and_base_manifest_install_the_wayland_gui_stack(self):
        kickstart = self.read("kickstart/feclora-live.ks")
        base = self.read("packages/base.txt")
        for package in ("cage", "gtk4", "libadwaita", "python3-gobject", "python3-textual"):
            self.assertIn(f"\n{package}\n", kickstart)
            self.assertIn(f"\n{package}\n", base)

    def test_welcome_window_is_fullscreen_wayland_and_reports_after_map(self):
        frontend = self.read("src/feclora/gui_gtk.py")
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', frontend)
        self.assertIn('os.environ.pop("DISPLAY", None)', frontend)
        self.assertIn("self.window.set_decorated(False)", frontend)
        self.assertIn("self.window.fullscreen()", frontend)
        self.assertIn(
            'self.window.connect("map", lambda _window: GLib.idle_add(self._report_boot_rendered))',
            frontend,
        )
        self.assertIn('Path("/run/feclora-gtk/ready")', frontend)
        self.assertIn('ready.write_text("rendered\\n", encoding="ascii")', frontend)
        ready_helper = self.read("src/feclora/data/feclora-gtk-ready")
        self.assertIn('while [ ! -f "$READY" ]', ready_helper)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", ready_helper)
        welcome = frontend[frontend.index("def _show_welcome"):frontend.index("def _language_changed")]
        self.assertIn("Idioma de la interfaz", welcome)
        self.assertIn("Distribución del teclado", welcome)

    def test_qemu_boot_smoke_provides_virtio_display_and_ready_channel(self):
        smoke = self.read("tests/vm/run-boot-smoke.py")
        self.assertIn('"virtio"', smoke)
        self.assertIn('"-vga"', smoke)
        self.assertIn('"virtio"', smoke)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", smoke)


if __name__ == "__main__":
    unittest.main()
