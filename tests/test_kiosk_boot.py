from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KioskBootConfigurationTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_gtk_weston_is_the_only_production_interface(self):
        service = self.read("src/feclora/data/feclora-gtk.service")
        kickstart = self.read("kickstart/feclora-live.ks")
        self.assertIn("ExecStart=/usr/bin/weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- /usr/bin/python3 -m feclora.gui_gtk", service)
        self.assertIn('enable feclora-gtk.service feclora-root-terminal.service', kickstart)
        self.assertIn('etc/systemd/system/feclora-gtk.service', kickstart)
        self.assertIn('usr/libexec/feclora/feclora-gtk-ready', kickstart)
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
        self.assertNotIn("\npython3-textual\n", kickstart)
        self.assertNotIn("\npython3-textual\n", base)
        self.assertTrue((ROOT / "src/feclora/data/feclora-gtk.service").is_file())
        self.assertTrue((ROOT / "src/feclora/data/feclora-gtk-ready").is_file())


    def test_legacy_textual_runtime_artifacts_are_removed(self):
        for relative in (
            "src/feclora/tui.py",
            "src/feclora/tui_api.py",
            "src/feclora/data/feclora-tui.service",
            "src/feclora/data/feclora-tui-ready",
            "tests/test_tui.py",
            "tests/test_tui_api.py",
            "requirements-test.txt",
            "docs/GTK4-MIGRATION.md",
        ):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_gtk_production_uses_weston_wayland_and_waits_for_render(self):
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
        self.assertLess(
            ready.index('if [ ! -c "$CHANNEL" ]'),
            ready.index("while [ ! -f"),
            "Physical boots without a virtio channel must not wait for the QEMU-only readiness marker.",
        )
        self.assertNotIn("--xwayland", service)
        self.assertIn("enable feclora-gtk.service", self.read("kickstart/feclora-live.ks"))

    def test_fedora45_kmscon_cannot_own_application_or_maintenance_vts(self):
        kickstart = self.read("kickstart/feclora-live.ks")
        gtk = self.read("src/feclora/data/feclora-gtk.service")
        terminal = self.read("src/feclora/data/feclora-root-terminal.service")
        self.assertIn(
            'mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service',
            kickstart,
        )
        self.assertIn("Conflicts=getty@tty1.service kmsconvt@tty1.service", gtk)
        self.assertIn("Conflicts=getty@tty2.service kmsconvt@tty2.service", terminal)
        self.assertIn("After=systemd-logind.service kmsconvt@tty2.service", terminal)
        self.assertIn("[Install]", terminal)
        self.assertIn("WantedBy=multi-user.target", terminal)
        self.assertNotIn("ExecStartPre=+/usr/bin/chvt 2", terminal)
        self.assertIn("enable feclora-root-terminal.service", kickstart)

    def test_gtk_source_is_native_wayland_fullscreen_and_boot_enabled(self):
        frontend = self.read("src/feclora/gui_gtk.py")
        self.assertLess(
            frontend.index('self.window.connect("map",'),
            frontend.index('self._show_welcome()'),
            "GTK must subscribe to the first map event before presenting its initial window.",
        )
        self.assertIn('"after-paint", self._on_first_frame_painted', frontend)
        self.assertIn("def _on_first_frame_painted(", frontend)
        self.assertIn("frame_clock.disconnect(self._boot_frame_clock_handler)", frontend)
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', frontend)
        self.assertIn('os.environ.pop("DISPLAY", None)', frontend)
        self.assertIn("self.window.set_decorated(False)", frontend)
        self.assertIn("self.window.fullscreen()", frontend)
        self.assertIn("Idioma de la interfaz", frontend)
        self.assertIn("Distribución del teclado", frontend)

    def test_qemu_boot_smoke_waits_for_rendered_interface(self):
        smoke = self.read("tests/vm/run-boot-smoke.py")
        ready = self.read("src/feclora/data/feclora-gtk-ready")
        self.assertIn('"virtio-serial-pci"', smoke)
        self.assertIn('"virtio"', smoke)
        self.assertIn("FECLORA_BOOT_SMOKE gtk-rendered", smoke)
        self.assertIn("FECLORA_BOOT_SMOKE gtk-rendered", ready)


if __name__ == "__main__":
    unittest.main()
