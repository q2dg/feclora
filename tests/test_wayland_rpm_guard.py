from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "build/verify-wayland-rpms.sh"


class WaylandRPMGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.db_path = self.root / "rpm-db.json"
        self.records = {
            "weston.rpm": {
                "name": "weston", "epoch": "1", "version": "15.0.1",
                "release": "99.fc45.feclora1",
                "source": "weston-15.0.1-99.fc45.feclora1.src.rpm",
                "files": ["/usr/bin/weston", "/usr/lib64/weston/kiosk-shell.so"],
                "requires": ["weston-libs", "libwayland-client.so.0"],
                "provides": ["weston"],
            },
            "weston-libs.rpm": {
                "name": "weston-libs", "epoch": "1", "version": "15.0.1",
                "release": "99.fc45.feclora1",
                "source": "weston-15.0.1-99.fc45.feclora1.src.rpm",
                "files": ["/usr/lib64/libweston-15/drm-backend.so"],
                "requires": ["libwayland-server.so.0", "libdrm.so.2", "libinput.so.10", "libseat.so.1"],
                "provides": ["libweston-15"],
            },
            "gtk4.rpm": {
                "name": "gtk4", "epoch": "1", "version": "4.24.1",
                "release": "99.fc45.feclora1",
                "source": "gtk4-4.24.1-99.fc45.feclora1.src.rpm",
                "files": [
                    "/usr/lib64/libgtk-4.so.1",
                    "/usr/lib64/girepository-1.0/GdkWayland-4.0.typelib",
                ],
                "requires": ["libwayland-client.so.0", "libxkbcommon.so.0"],
                "provides": ["gtk4"],
            },
            "libadwaita.rpm": {
                "name": "libadwaita", "epoch": "1", "version": "1.10.0",
                "release": "99.fc45.feclora1",
                "source": "libadwaita-1.10.0-99.fc45.feclora1.src.rpm",
                "files": ["/usr/lib64/libadwaita-1.so.0"],
                "requires": ["gtk4 >= 4.24.1"],
                "provides": ["libadwaita"],
            },
            "cairo.rpm": {
                "name": "cairo", "epoch": "1", "version": "1.18.6",
                "release": "99.fc45.feclora1",
                "source": "cairo-1.18.6-99.fc45.feclora1.src.rpm",
                "files": ["/usr/lib64/libcairo.so.2"],
                "requires": ["libpixman-1.so.0", "libfontconfig.so.1", "libfreetype.so.6"],
                "provides": ["libcairo.so.2"],
            },
            "cairo-gobject.rpm": {
                "name": "cairo-gobject", "epoch": "1", "version": "1.18.6",
                "release": "99.fc45.feclora1",
                "source": "cairo-1.18.6-99.fc45.feclora1.src.rpm",
                "files": ["/usr/lib64/libcairo-gobject.so.2"],
                "requires": ["cairo = 1:1.18.6-99.fc45.feclora1"],
                "provides": ["libcairo-gobject.so.2"],
            },
            "gtk4-devel.rpm": {
                "name": "gtk4-devel", "epoch": "1", "version": "4.24.1",
                "release": "99.fc45.feclora1",
                "source": "gtk4-4.24.1-99.fc45.feclora1.src.rpm",
                "files": [
                    "/usr/include/gtk-4.0/gdk/wayland/gdkwaylanddisplay.h",
                    "/usr/lib64/pkgconfig/gtk4-wayland.pc",
                ],
                "requires": ["gtk4 = 1:4.24.1-99.fc45.feclora1", "wayland-devel"],
                "provides": ["pkgconfig(gtk4)"],
            },
            "cairo-devel.rpm": {
                "name": "cairo-devel", "epoch": "1", "version": "1.18.6",
                "release": "99.fc45.feclora1",
                "source": "cairo-1.18.6-99.fc45.feclora1.src.rpm",
                "files": [
                    "/usr/include/cairo/cairo.h",
                    "/usr/lib64/pkgconfig/cairo.pc",
                ],
                "requires": ["cairo = 1:1.18.6-99.fc45.feclora1"],
                "provides": ["pkgconfig(cairo)"],
            },
            "cairo-gobject-devel.rpm": {
                "name": "cairo-gobject-devel", "epoch": "1", "version": "1.18.6",
                "release": "99.fc45.feclora1",
                "source": "cairo-1.18.6-99.fc45.feclora1.src.rpm",
                "files": [
                    "/usr/include/cairo/cairo-gobject.h",
                    "/usr/lib64/pkgconfig/cairo-gobject.pc",
                ],
                "requires": ["cairo-gobject = 1:1.18.6-99.fc45.feclora1"],
                "provides": ["pkgconfig(cairo-gobject)"],
            },
            "weston-devel.rpm": {
                "name": "weston-devel", "epoch": "1", "version": "15.0.1",
                "release": "99.fc45.feclora1",
                "source": "weston-15.0.1-99.fc45.feclora1.src.rpm",
                "files": ["/usr/include/libweston-15/libweston.h", "/usr/lib64/pkgconfig/libweston-15.pc"],
                "requires": ["weston-libs = 1:15.0.1-99.fc45.feclora1"],
                "provides": ["pkgconfig(libweston-15)"],
            },
        }
        fake_rpm = self.fake_bin / "rpm"
        fake_rpm.write_text(
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

database = json.loads(Path(os.environ["FAKE_RPM_DB"]).read_text(encoding="utf-8"))
args = sys.argv[1:]
if args[:2] == ["-qp", "--qf"]:
    record = database[Path(args[-1]).name]
    if "%{SOURCERPM}" in args[2]:
        print("|".join((record["epoch"], record["version"], record["release"], record["source"])))
    else:
        print(record["name"])
elif args[0] == "-qpl":
    print("\\n".join(database[Path(args[-1]).name]["files"]))
elif args[0] == "-qp" and args[1] in (
    "--requires", "--provides", "--recommends", "--suggests", "--supplements", "--enhances"
):
    record = database[Path(args[-1]).name]
    key = args[1][2:]
    print("\\n".join(record.get(key, [])))
else:
    raise SystemExit("unsupported fake rpm invocation: " + repr(args))
""",
            encoding="utf-8",
        )
        fake_rpm.chmod(0o755)
        self.rpm_paths = []
        for filename in self.records:
            path = self.root / filename
            path.write_bytes(b"fake rpm fixture")
            self.rpm_paths.append(path)
        self._write_database()

    def tearDown(self):
        self.temp.cleanup()

    def _write_database(self):
        self.db_path.write_text(json.dumps(self.records), encoding="utf-8")

    def _run(self, paths=None):
        environment = os.environ.copy()
        environment["PATH"] = str(self.fake_bin) + os.pathsep + environment.get("PATH", "")
        environment["FAKE_RPM_DB"] = str(self.db_path)
        selected = paths if paths is not None else self.rpm_paths[:6]
        return subprocess.run(
            ["bash", str(GUARD), *(str(path) for path in selected)],
            cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
        )

    def test_accepts_fedora45_wayland_only_rebuilds(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Strict X11-free Fedora 45", result.stdout)

    def test_accepts_optional_x11_free_development_rpms(self):
        result = self._run(self.rpm_paths)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_weston_development_subpackage_when_it_is_x11_free(self):
        result = self._run(self.rpm_paths)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_wayland_libxkbcommon_runtime_dependency(self):
        self.records["gtk4.rpm"]["requires"].append("libxkbcommon.so.0")
        self._write_database()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_xwayland_module(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/lib64/libweston-15/xwayland.so")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_weston_x11_backend(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/lib64/libweston-15/x11-backend.so")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_gdk_x11_typelib(self):
        self.records["gtk4.rpm"]["files"].append("/usr/lib64/girepository-1.0/GdkX11-4.0.typelib")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_gdk_x11_header(self):
        self.records["gtk4-devel.rpm"]["files"].append("/usr/include/gtk-4.0/gdk/gdkx11display.h")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_x11_shared_library_payload(self):
        self.records["gtk4.rpm"]["files"].append("/usr/lib64/libXcursor.so.1")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_xcb_shared_library_payload(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/lib64/libxcb.so.1")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_xkbcommon_x11_shared_library_payload(self):
        self.records["gtk4.rpm"]["files"].append("/usr/lib64/libxkbcommon-x11.so.0")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_x11_headers(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/include/libweston-15/backend-x11.h")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_xwayland_api_header(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/include/libweston-15/xwayland-api.h")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_gtk4_x11_pkgconfig_metadata(self):
        self.records["gtk4-devel.rpm"]["files"].append("/usr/lib64/pkgconfig/gtk4-x11.pc")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_cairo_xlib_header(self):
        self.records["cairo-devel.rpm"]["files"].append("/usr/include/cairo/cairo-xlib.h")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_cairo_xcb_pkgconfig_file(self):
        self.records["cairo-devel.rpm"]["files"].append("/usr/lib64/pkgconfig/cairo-xcb.pc")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_x11_capability_in_provides(self):
        self.records["gtk4-devel.rpm"]["provides"].append("pkgconfig(gtk4-x11)")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("advertises an X11 capability", result.stderr)

    def test_rejects_cairo_xlib_capability_in_provides(self):
        self.records["cairo-devel.rpm"]["provides"].append("pkgconfig(cairo-xlib)")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("advertises an X11 capability", result.stderr)

    def test_rejects_cairo_x11_runtime_dependency(self):
        self.records["cairo.rpm"]["requires"].append("libX11.so.6()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_cairo_xcb_runtime_dependency(self):
        self.records["cairo.rpm"]["requires"].append("libxcb.so.1()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_xkbcommon_x11_runtime_dependency(self):
        self.records["gtk4.rpm"]["requires"].append("libxkbcommon-x11.so.0()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_xkbcommon_x11_pkgconfig_dependency(self):
        self.records["gtk4-devel.rpm"]["requires"].append("pkgconfig(xkbcommon-x11)")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_xwayland_executable(self):
        self.records["weston.rpm"]["files"].append("/usr/bin/Xwayland")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)

    def test_rejects_openbox_package(self):
        self.records["gtk4-devel.rpm"]["name"] = "openbox"
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Forbidden X11 package", result.stderr)

    def test_rejects_x11_runtime_dependency(self):
        self.records["gtk4.rpm"]["requires"].append("libX11.so.6()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_xcb_runtime_dependency(self):
        self.records["weston-libs.rpm"]["requires"].append("libxcb.so.1()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_mesa_x11_xcb_and_shared_memory_dependencies(self):
        self.records["weston-libs.rpm"]["requires"].extend([
            "libX11-xcb.so.1()(64bit)", "libxshmfence.so.1()(64bit)",
        ])
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_x11_pkgconfig_dependency(self):
        self.records["gtk4-devel.rpm"]["requires"].append("pkgconfig(x11)")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_forbidden_x11_package(self):
        self.records["gtk4-devel.rpm"]["name"] = "libX11"
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Forbidden X11 package", result.stderr)

    def test_rejects_cairo_xlib_subpackage(self):
        self.records["cairo-devel.rpm"]["name"] = "cairo-xlib"
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Forbidden X11 package", result.stderr)

    def test_rejects_weston_without_libseat_launcher_dependency(self):
        self.records["weston-libs.rpm"]["requires"] = [
            item for item in self.records["weston-libs.rpm"]["requires"]
            if not item.startswith("libseat")
        ]
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("libseat launcher support is missing", result.stderr)


    def test_rejects_non_fedora45_source_release(self):
        self.records["weston-libs.rpm"]["release"] = "1.el10.feclora1"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact Feclora rebuild release 99.fc45.feclora1", result.stderr)

    def test_rejects_unmarked_fedora_release(self):
        self.records["weston.rpm"]["release"] = "3.fc45"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact Feclora rebuild release 99.fc45.feclora1", result.stderr)

    def test_rejects_unexpected_source_rpm_provenance(self):
        self.records["gtk4.rpm"]["source"] = "gtk4-4.24.1-1.fc45.src.rpm"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected Fedora 45 Feclora source RPM provenance", result.stderr)

    def test_rejects_binary_package_from_mismatched_source_family(self):
        self.records["gtk4.rpm"]["source"] = "weston-15.0.1-99.fc45.feclora1.src.rpm"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not belong to the weston source RPM family", result.stderr)

    def test_rejects_stock_epoch_graphics_rpm(self):
        self.records["gtk4.rpm"]["epoch"] = "0"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Feclora graphics RPM epoch 1", result.stderr)

    def test_rejects_wrong_upstream_version(self):
        self.records["gtk4.rpm"]["version"] = "4.24.2"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("version 4.24.1", result.stderr)

    def test_requires_all_six_runtime_packages(self):
        result = self._run(self.rpm_paths[:5])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Supply Weston, GTK4, libadwaita, Cairo", result.stderr)


    def test_rejects_xext_and_xrender_pkgconfig_requirements(self):
        self.records["cairo-devel.rpm"]["requires"].extend(["pkgconfig(xext)", "pkgconfig(xrender)"])
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 requirement", result.stderr)

    def test_rejects_xext_pkgconfig_file(self):
        self.records["cairo-devel.rpm"]["files"].append("/usr/lib64/pkgconfig/xext.pc")
        self._write_database()
        result = self._run(self.rpm_paths)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden X11 backend", result.stderr)


if __name__ == "__main__":
    unittest.main()
