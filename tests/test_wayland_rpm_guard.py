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
                "name": "weston",
                "files": ["/usr/bin/weston", "/usr/lib64/weston/kiosk-shell.so"],
                "requires": ["weston-libs", "libwayland-client.so.0"],
            },
            "weston-libs.rpm": {
                "name": "weston-libs",
                "files": ["/usr/lib64/libweston-15/drm-backend.so"],
                "requires": ["libwayland-server.so.0", "libdrm.so.2"],
            },
            "gtk4.rpm": {
                "name": "gtk4",
                "files": [
                    "/usr/lib64/libgtk-4.so.1",
                    "/usr/lib64/girepository-1.0/GdkWayland-4.0.typelib",
                ],
                "requires": ["libwayland-client.so.0"],
            },
            "libadwaita.rpm": {
                "name": "libadwaita",
                "files": ["/usr/lib64/libadwaita-1.so.0"],
                "requires": ["gtk4 >= 4.24.1"],
            },
            "gtk4-devel.rpm": {
                "name": "gtk4-devel",
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
    print(database[Path(args[-1]).name]["name"])
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
            ["bash", str(GUARD), *(str(path) for path in (paths or self.rpm_paths))],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_accepts_wayland_only_runtime_rpms(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wayland-only RPM audit passed", result.stdout)

    def test_rejects_weston_x11_backend_file(self):
        self.records["weston-libs.rpm"]["files"].append(
            "/usr/lib64/libweston-15/x11-backend.so"
        )
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("x11-backend.so", result.stderr)

    def test_rejects_gtk_gdk_x11_typelib(self):
        self.records["gtk4.rpm"]["files"].append(
            "/usr/lib64/girepository-1.0/GdkX11-4.0.typelib"
        )
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GdkX11-4.0.typelib", result.stderr)

    def test_rejects_direct_x11_library_dependency(self):
        self.records["gtk4.rpm"]["requires"].append("libX11.so.6()(64bit)")
        self._write_database()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("libX11.so.6", result.stderr)

    def test_audits_optional_gtk4_development_rpm(self):
        extra = self.root / "gtk4-devel.rpm"
        extra.write_bytes(b"fake rpm fixture")
        result = self._run([*self.rpm_paths, extra])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_x11_build_dependency_in_optional_development_rpm(self):
        self.records["gtk4-devel.rpm"]["requires"].append("pkgconfig(x11)")
        self._write_database()
        extra = self.root / "gtk4-devel.rpm"
        extra.write_bytes(b"fake rpm fixture")
        result = self._run([*self.rpm_paths, extra])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pkgconfig(x11)", result.stderr)

    def test_requires_all_four_runtime_packages(self):
        result = self._run(self.rpm_paths[:-1])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly four RPMs", result.stderr)


if __name__ == "__main__":
    unittest.main()
