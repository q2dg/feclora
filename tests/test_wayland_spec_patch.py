from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCHER_PATH = ROOT / "build/patch-fedora-wayland-spec.py"
SPEC = importlib.util.spec_from_file_location("fedora_wayland_spec_patcher", PATCHER_PATH)
assert SPEC is not None and SPEC.loader is not None
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


class FedoraWaylandSpecPatcherTests(unittest.TestCase):
    def test_cairo_disables_xlib_xcb_and_removes_x11_metadata(self):
        source = """Name: cairo
Version: 1.18.6
Release: %autorelease
BuildRequires: pkgconfig(x11)
BuildRequires: pkgconfig(xcb)
BuildRequires: pkgconfig(xcb-render)
BuildRequires: pkgconfig(xcb-shm)
BuildRequires: pkgconfig(xext)
Requires: pkgconfig(xrender)
Requires: libX11-devel
Requires: pkgconfig(cairo-xlib)
%description
Cairo
%build
%meson -Dtests=disabled
%install
%meson_install
%files devel
%{_includedir}/cairo/cairo.h
%{_includedir}/cairo/cairo-xlib.h
%{_includedir}/cairo/cairo-xcb.h
%{_libdir}/pkgconfig/cairo.pc
%{_libdir}/pkgconfig/cairo-xlib.pc
%{_libdir}/pkgconfig/cairo-xcb.pc
%files
%{_libdir}/libcairo.so.2
"""
        patched = PATCHER.patch_spec_text("cairo", source)
        build = patched.split("%install", 1)[0]
        for flag in ("-Dxlib=disabled", "-Dxcb=disabled", "-Dxlib-xcb=disabled"):
            self.assertIn(flag, build)
        self.assertIn("%{_includedir}/cairo/cairo.h", patched)
        self.assertIn("%{_libdir}/pkgconfig/cairo.pc", patched)
        for forbidden in (
            "pkgconfig(x11)", "pkgconfig(xcb)", "pkgconfig(xcb-render)", "pkgconfig(xcb-shm)",
            "pkgconfig(xext)", "pkgconfig(xrender)", "libX11-devel", "pkgconfig(cairo-xlib)", "cairo-xlib.h", "cairo-xcb.h",
            "cairo-xlib.pc", "cairo-xcb.pc",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, patched)

    def test_weston_disables_x11_and_keeps_drm_kiosk(self):
        source = """Name: weston
Version: 15.0.1
Release: %autorelease
%description
Weston
%build
%meson \\
  -Dremoting=false
%install
%meson_install
"""
        patched = PATCHER.patch_spec_text("weston", source)
        build = patched.split("%install", 1)[0]
        for flag in ("-Dxwayland=false", "-Dbackend-x11=false", "-Dbackend-drm=true", "-Dshell-kiosk=true", "-Dsystemd=true", "-Drenderer-gl=false"):
            self.assertIn(flag, build)
        self.assertIn("Epoch:          1", patched)
        self.assertIn("Release:        99%{?dist}.feclora1", patched)
        self.assertIn("-Dremoting=false", build)
        self.assertNotIn("-Dlauncher-libseat", build)

    def test_gtk_disables_gdk_x11_and_enables_wayland(self):
        source = """Name: gtk4
Version: 4.24.1
Release: %autorelease
%build
%meson -Dintrospection=enabled
%install
%meson_install
"""
        patched = PATCHER.patch_spec_text("gtk4", source)
        build = patched.split("%install", 1)[0]
        self.assertIn("-Dx11-backend=false", build)
        self.assertIn("-Dwayland-backend=true", build)
        self.assertIn("-Dvulkan=disabled", build)
        self.assertIn("Epoch:          1", patched)

    def test_libadwaita_uses_exact_fedora45_version_and_custom_release(self):
        source = """Name: libadwaita
Version: 1.10.0
Release: %autorelease
%build
%meson
%install
%meson_install
"""
        patched = PATCHER.patch_spec_text("libadwaita", source)
        self.assertIn("Epoch:          1", patched)
        self.assertIn("Release:        99%{?dist}.feclora1", patched)
        self.assertIn("%meson", patched)

    def test_overwrites_existing_epoch_with_feclora_epoch(self):
        source = "Name: gtk4\nEpoch: 0\nVersion: 4.24.1\nRelease: 1%{?dist}\n%build\n%meson\n"
        patched = PATCHER.patch_spec_text("gtk4", source)
        self.assertEqual(patched.count("Epoch:"), 1)
        self.assertIn("Epoch:          1", patched)

    def test_rejects_unexpected_fedora_source_version(self):
        with self.assertRaisesRegex(ValueError, "must be 4.24.1"):
            PATCHER.patch_spec_text("gtk4", "Name: gtk4\nVersion: 4.24.2\nRelease: 1%{?dist}\n%build\n%meson\n")

    def test_rejects_spec_without_meson_build_invocation(self):
        with self.assertRaisesRegex(ValueError, "no %meson invocation"):
            PATCHER.patch_spec_text("weston", "Name: weston\nVersion: 15.0.1\nRelease: 1%{?dist}\n%build\nmake\n%install\n")

    def test_rejects_unknown_package(self):
        with self.assertRaisesRegex(ValueError, "unsupported Fedora package"):
            PATCHER.patch_spec_text("xorg", "Name: xorg\n")


if __name__ == "__main__":
    unittest.main()
