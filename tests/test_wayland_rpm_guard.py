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
                "name": "weston", "epoch": "1",
                "version": "15.0.1", "release": "99.fc45.feclora1", "source": "weston-15.0.1-99.fc45.feclora1.src.rpm",
                "files": ["/usr/bin/weston", "/usr/lib64/weston/kiosk-shell.so"],
                "requires": ["weston-libs", "libwayland-client.so.0"],
            },
            "weston-libs.rpm": {
                "name": "weston-libs", "epoch": "1",
                "version": "15.0.1", "release": "99.fc45.feclora1", "source": "weston-15.0.1-99.fc45.feclora1.src.rpm",
                "files": ["/usr/lib64/libweston-15/drm-backend.so"],
                "requires": ["libwayland-server.so.0", "libdrm.so.2", "libinput.so.10"],
            },
            "gtk4.rpm": {
                "name": "gtk4", "epoch": "1",
                "version": "4.24.1", "release": "99.fc45.feclora1", "source": "gtk4-4.24.1-99.fc45.feclora1.src.rpm",
                "files": [
                    "/usr/lib64/libgtk-4.so.1",
                    "/usr/lib64/girepository-1.0/GdkWayland-4.0.typelib",
                ],
                "requires": ["libwayland-client.so.0", "libxkbcommon.so.0"],
            },
            "libadwaita.rpm": {
                "name": "libadwaita", "epoch": "1",
                "version": "1.10.0", "release": "99.fc45.feclora1", "source": "libadwaita-1.10.0-99.fc45.feclora1.src.rpm",
                "files": ["/usr/lib64/libadwaita-1.so.0"],
                "requires": ["gtk4 >= 4.24.1"],
            },
            "gtk4-devel.rpm": {
                "name": "gtk4-devel", "epoch": "1",
                "version": "4.24.1", "release": "99.fc45.feclora1", "source": "gtk4-4.24.1-99.fc45.feclora1.src.rpm",
                "files": [
                    "/usr/include/gtk-4.0/gdk/wayland/gdkwaylanddisplay.h",
                    "/usr/lib64/pkgconfig/gtk4-wayland.pc",
                ],
                "requires": ["gtk4 = 4.24.1", "wayland-devel"],
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
elif args[0] == "-qpR":
    print("\\n".join(database[Path(args[-1]).name]["requires"]))
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
        return subprocess.run(
            ["bash", str(GUARD), *(str(path) for path in (paths if paths is not None else self.rpm_paths[:4]))],
            cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
        )

    def test_accepts_fedora45_wayland_only_rebuilds(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Strict X11-free Fedora 45", result.stdout)

    def test_accepts_optional_x11_free_development_rpm(self):
        result = self._run([*self.rpm_paths[:4], self.rpm_paths[4]])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_xwayland_module(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/lib64/libweston-15/xwayland.so")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_weston_x11_backend(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/lib64/libweston-15/x11-backend.so")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_gdk_x11_typelib(self):
        self.records["gtk4.rpm"]["files"].append("/usr/lib64/girepository-1.0/GdkX11-4.0.typelib")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_x11_shared_library_payload(self):
        self.records["gtk4.rpm"]["files"].append("/usr/lib64/libXcursor.so.1")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_xcb_shared_library_payload(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/lib64/libxcb.so.1")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_xkbcommon_x11_shared_library_payload(self):
        self.records["gtk4.rpm"]["files"].append("/usr/lib64/libxkbcommon-x11.so.0")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_x11_headers(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/include/libweston-15/backend-x11.h")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_xwayland_api_header(self):
        self.records["weston-libs.rpm"]["files"].append("/usr/include/libweston-15/xwayland-api.h")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_gtk4_x11_pkgconfig_metadata(self):
        self.records["gtk4-devel.rpm"]["files"].append("/usr/lib64/pkgconfig/gtk4-x11.pc")
        self._write_database()
        result = self._run([*self.rpm_paths[:4], self.rpm_paths[4]])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_xkbcommon_x11_runtime_dependency(self):
        self.records["gtk4.rpm"]["requires"].append("libxkbcommon-x11.so.0()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 runtime or build dependency", result.stderr)

    def test_rejects_xkbcommon_x11_pkgconfig_dependency(self):
        self.records["gtk4-devel.rpm"]["requires"].append("pkgconfig(xkbcommon-x11)")
        self._write_database()
        result = self._run([*self.rpm_paths[:4], self.rpm_paths[4]])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 runtime or build dependency", result.stderr)

    def test_rejects_xwayland_executable(self):
        self.records["weston.rpm"]["files"].append("/usr/bin/Xwayland")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 backend", result.stderr)

    def test_rejects_openbox_package(self):
        self.records["gtk4-devel.rpm"]["name"] = "openbox"
        self._write_database()
        result = self._run([*self.rpm_paths[:4], self.rpm_paths[4]])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Forbidden X11 package", result.stderr)

    def test_rejects_x11_runtime_dependency(self):
        self.records["gtk4.rpm"]["requires"].append("libX11.so.6()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 runtime or build dependency", result.stderr)

    def test_rejects_xcb_runtime_dependency(self):
        self.records["weston-libs.rpm"]["requires"].append("libxcb.so.1()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 runtime or build dependency", result.stderr)

    def test_rejects_x11_pkgconfig_dependency(self):
        self.records["gtk4-devel.rpm"]["requires"].append("pkgconfig(x11)")
        self._write_database()
        result = self._run([*self.rpm_paths[:4], self.rpm_paths[4]])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 runtime or build dependency", result.stderr)

    def test_rejects_forbidden_x11_package(self):
        self.records["gtk4-devel.rpm"]["name"] = "libX11"
        self._write_database()
        result = self._run([*self.rpm_paths[:4], self.rpm_paths[4]])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Forbidden X11 package", result.stderr)

    def test_rejects_non_fedora45_source_release(self):
        self.records["weston-libs.rpm"]["release"] = "1.el10.feclora1"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reserved 99.fc45.feclora rebuild release", result.stderr)

    def test_rejects_unmarked_fedora_release(self):
        self.records["weston.rpm"]["release"] = "3.fc45"
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reserved 99.fc45.feclora rebuild release", result.stderr)

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

    def test_requires_all_four_runtime_packages(self):
        result = self._run(self.rpm_paths[:3])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Supply weston, weston-libs, gtk4 and libadwaita", result.stderr)


if __name__ == "__main__":
    unittest.main()
