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
        self.assertIn('etc/systemd/system/feclora-gtk.service', kickstart)
        self.assertIn('usr/libexec/feclora/feclora-gtk-ready', kickstart)
        self.assertIn('feclora-tui.service', kickstart)
        self.assertTrue((ROOT / "src/feclora/data/feclora-gtk.service").exists())

    def test_official_fedora_gtk_weston_stack_is_selected(self):
        kickstart = self.read("kickstart/feclora-live.ks")
        base = self.read("packages/base.txt")
        for package in ("weston", "weston-libs", "gtk4", "libadwaita", "python3-gobject"):
            self.assertIn(f"\n{package}\n", kickstart)
            self.assertIn(f"\n{package}\n", base)
        self.assertNotIn("\ncage\n", kickstart)
        self.assertNotIn("\ncage\n", base)
        self.assertIn("-xorg-x11-server-Xwayland", kickstart)
        self.assertIn("-xorg-x11-server-Xorg", kickstart)
        self.assertNotIn("xorg-x11-server-Xwayland", base)
        self.assertNotIn("xorg-x11-server-Xorg", base)
        self.assertIn("\npython3-textual\n", kickstart)
        self.assertIn("\npython3-textual\n", base)
        self.assertTrue((ROOT / "src/feclora/data/feclora-gtk.service").is_file())
        self.assertTrue((ROOT / "src/feclora/data/feclora-gtk-ready").is_file())


    def test_gtk_candidate_uses_weston_wayland_and_waits_for_render(self):
        service = self.read("src/feclora/data/feclora-gtk.service")
        ready = self.read("src/feclora/data/feclora-gtk-ready")
        self.assertIn("PAMName=login", service)
        self.assertIn("Environment=GDK_BACKEND=wayland", service)
        self.assertIn("Environment=LIBSEAT_BACKEND=logind", service)
        self.assertIn("UnsetEnvironment=DISPLAY XAUTHORITY", service)
        self.assertIn(
            "weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- /usr/bin/python3 -m feclora.gui_gtk",
            service,
        )
        self.assertIn("TTYPath=/dev/tty1", service)
        self.assertIn("ExecStartPost=+/usr/libexec/feclora/feclora-gtk-ready", service)
        self.assertIn("FECLORA_BOOT_SMOKE gtk-rendered", ready)
        self.assertNotIn("--xwayland", service)
        self.assertNotIn("enable feclora-gtk.service", self.read("kickstart/feclora-live.ks"))

    def test_fedora45_kmscon_cannot_own_application_or_maintenance_vts(self):
        kickstart = self.read("kickstart/feclora-live.ks")
        tui = self.read("src/feclora/data/feclora-tui.service")
        terminal = self.read("src/feclora/data/feclora-root-terminal.service")
        self.assertIn(
            'mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service',
            kickstart,
        )
        self.assertIn("Conflicts=getty@tty1.service kmsconvt@tty1.service", tui)
        self.assertIn("Conflicts=getty@tty2.service kmsconvt@tty2.service", terminal)
        self.assertIn("After=systemd-logind.service kmsconvt@tty2.service", terminal)

    def test_gtk_source_is_native_wayland_and_fullscreen_but_not_boot_enabled(self):
        frontend = self.read("src/feclora/gui_gtk.py")
        self.assertLess(
            frontend.index('self.window.connect("map",'),
            frontend.index('self._show_welcome()'),
            "GTK must subscribe to the first map event before presenting its initial window.",
        )
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', frontend)
        self.assertIn('os.environ.pop("DISPLAY", None)', frontend)
        self.assertIn("self.window.set_decorated(False)", frontend)
        self.assertIn("self.window.fullscreen()", frontend)
        self.assertIn("Idioma de la interfaz", frontend)
        self.assertIn("Distribución del teclado", frontend)

    def test_weston_target_uses_official_fedora_packages_without_xwayland_server(self):
        migration = self.read("docs/GTK4-MIGRATION.md")
        self.assertIn("Fedora 45's official runtime RPMs", migration)
        self.assertIn("xorg-x11-server-Xwayland", migration)
        self.assertIn("The presence of optional X11 client backends", migration)
        self.assertIn("does not mean an X server is installed or running", migration)
        self.assertIn("--no-config -B drm --shell=kiosk-shell.so", migration)
        self.assertIn("Then remove Textual and obsolete text-boot checks.", migration)

    def test_qemu_boot_smoke_waits_for_rendered_interface(self):
        smoke = self.read("tests/vm/run-boot-smoke.py")
        ready = self.read("src/feclora/data/feclora-gtk-ready")
        self.assertIn('"virtio-serial-pci"', smoke)
        self.assertIn('"virtio"', smoke)
        self.assertIn("FECLORA_BOOT_SMOKE gtk-rendered", smoke)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", smoke)
        self.assertIn("FECLORA_BOOT_SMOKE gtk-rendered", ready)


if __name__ == "__main__":
    unittest.main()
