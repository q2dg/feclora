from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KioskBootConfigurationTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_textual_remains_production_until_gtk_acceptance(self):
        service = self.read("src/feclora/data/feclora-tui.service")
        kickstart = self.read("kickstart/feclora-live.ks")
        base = self.read("packages/base.txt")
        self.assertIn("ExecStart=/usr/bin/python3 -m feclora.tui", service)
        self.assertIn("python3-textual", kickstart)
        self.assertIn("python3-textual", base)
        self.assertIn('enable feclora-tui.service feclora-root-terminal.service', kickstart)
        self.assertNotIn('enable feclora-gtk.service', kickstart)
        self.assertIn('feclora-gtk.service', kickstart)  # candidate staged, not enabled
        self.assertIn('feclora-tui.service', kickstart)

    def test_stock_graphical_packages_are_not_in_the_live_image(self):
        kickstart = self.read("kickstart/feclora-live.ks")
        base = self.read("packages/base.txt")
        for package in ("weston", "weston-libs", "gtk4", "libadwaita"):
            self.assertNotIn(f"\n{package}\n", kickstart)
            self.assertNotIn(f"\n{package}\n", base)
        candidate = self.read("packages/wayland-candidate-runtime.txt")
        self.assertNotIn("\npython3-gobject\n", kickstart)
        self.assertNotIn("\npython3-gobject\n", base)
        self.assertIn("\npython3-gobject\n", candidate)
        self.assertIn("\npython3-cairo\n", candidate)
        for package in ("cairo", "cairo-gobject", "weston", "weston-libs", "gtk4", "libadwaita"):
            self.assertIn(f"\n{package}\n", candidate)
        self.assertIn("-xorg-x11-server-Xwayland", kickstart)
        self.assertIn("-xorg-x11-server-Xorg", kickstart)
        for forbidden in ("openbox", "cage", "xorg-x11-server-Xwayland", "xorg-x11-server-Xorg"):
            self.assertNotIn(f"\n{forbidden}\n", base)

    def test_textual_first_render_and_tty_ownership(self):
        service = self.read("src/feclora/data/feclora-tui.service")
        ready = self.read("src/feclora/data/feclora-tui-ready")
        self.assertIn("TTYPath=/dev/tty1", service)
        self.assertIn("Conflicts=getty@tty1.service", service)
        self.assertIn("kmsconvt@tty1.service", service)
        self.assertIn("ExecStartPost=+/usr/libexec/feclora/feclora-tui-ready", service)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", ready)

    def test_gtk_candidate_is_wayland_only_and_not_enabled(self):
        service = self.read("src/feclora/data/feclora-gtk.service")
        source = self.read("src/feclora/gui_gtk.py")
        kickstart = self.read("kickstart/feclora-live.ks")
        self.assertIn("Environment=GDK_BACKEND=wayland", service)
        self.assertIn("Environment=GSK_RENDERER=cairo", service)
        self.assertIn("--renderer=pixman", service)
        self.assertIn("UnsetEnvironment=DISPLAY XAUTHORITY WAYLAND_DISPLAY", service)
        self.assertIn("--no-config -B drm --shell=kiosk-shell.so", service)
        self.assertNotIn("--xwayland", service)
        self.assertIn('os.environ["GDK_BACKEND"] = "wayland"', source)
        self.assertIn('os.environ.pop("DISPLAY", None)', source)
        self.assertIn('os.environ.pop("XAUTHORITY", None)', source)
        self.assertIn('if not os.environ.get("WAYLAND_DISPLAY")', source)
        self.assertNotIn('enable feclora-gtk.service', kickstart)

    def test_tty2_remains_independent_root_maintenance(self):
        terminal = self.read("src/feclora/data/feclora-root-terminal.service")
        kickstart = self.read("kickstart/feclora-live.ks")
        self.assertIn("TTYPath=/dev/tty2", terminal)
        self.assertIn("Conflicts=getty@tty2.service kmsconvt@tty2.service", terminal)
        self.assertIn("enable feclora-tui.service feclora-root-terminal.service", kickstart)
        self.assertIn("mask getty@tty1.service getty@tty2.service", kickstart)
        self.assertIn(
            "mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service",
            kickstart,
        )

    def test_boot_smoke_expects_textual_render_marker(self):
        smoke = self.read("tests/vm/run-boot-smoke.py")
        ready = self.read("src/feclora/data/feclora-tui-ready")
        self.assertIn("FECLORA_BOOT_SMOKE rendered", smoke)
        self.assertIn("FECLORA_BOOT_SMOKE rendered", ready)
        self.assertNotIn("gtk-rendered", smoke)


if __name__ == "__main__":
    unittest.main()
