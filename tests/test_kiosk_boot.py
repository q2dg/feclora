from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KioskBootConfigurationTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_textual_remains_production_until_gtk_weston_parity(self):
        service = self.read("src/feclora/data/feclora-tui.service")
        kickstart = self.read("kickstart/feclora-live.ks")
        self.assertIn("ExecStart=/usr/bin/python3 -m feclora.tui", service)
        self.assertIn('enable feclora-tui.service', kickstart)
        self.assertNotIn('enable feclora-gtk.service', kickstart)
        self.assertIn('feclora-tui.service', kickstart)

    def test_no_cage_or_stock_gtk_weston_stack_is_shipped_early(self):
        kickstart = self.read("kickstart/feclora-live.ks")
        base = self.read("packages/base.txt")
        for package in ("cage", "weston", "weston-libs", "gtk4", "libadwaita", "python3-gobject"):
            self.assertNotIn(f"\n{package}\n", kickstart)
            self.assertNotIn(f"\n{package}\n", base)
        self.assertIn("\npython3-textual\n", kickstart)
        self.assertIn("\npython3-textual\n", base)
        self.assertFalse((ROOT / "src/feclora/data/feclora-gtk.service").exists())
        self.assertFalse((ROOT / "src/feclora/data/feclora-gtk-ready").exists())

    def test_gtk_source_is_native_wayland_and_fullscreen_but_not_boot_enabled(self):
        frontend = self.read("src/feclora/gui_gtk.py")
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', frontend)
        self.assertIn('os.environ.pop("DISPLAY", None)', frontend)
        self.assertIn("self.window.set_decorated(False)", frontend)
        self.assertIn("self.window.fullscreen()", frontend)
        self.assertIn("Idioma de la interfaz", frontend)
        self.assertIn("Distribución del teclado", frontend)

    def test_weston_target_is_documented_as_x11_disabled_build(self):
        migration = self.read("docs/GTK4-MIGRATION.md")
        self.assertIn("-Dxwayland=false -Dbackend-x11=false", migration)
        self.assertIn("-Dx11-backend=false -Dwayland-backend=true", migration)
        self.assertIn("--no-config -B drm --shell=kiosk-shell.so", migration)
        self.assertIn("Then remove Textual and obsolete text-boot checks.", migration)

    def test_qemu_boot_smoke_waits_for_rendered_interface(self):
        smoke = self.read("tests/vm/run-boot-smoke.py")
        ready = self.read("src/feclora/data/feclora-tui-ready")
        self.assertIn('"virtio-serial-pci"', smoke)
        self.assertIn('"virtio"', smoke)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", smoke)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", ready)


if __name__ == "__main__":
    unittest.main()
