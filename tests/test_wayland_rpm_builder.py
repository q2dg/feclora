from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "build/build-wayland-rpms.sh"


class WaylandRPMBuilderTests(unittest.TestCase):
    def test_uses_exact_fedora_45_source_release_tags(self):
        source = BUILDER.read_text(encoding="utf-8")
        for release_tag in (
            "cairo-1.18.6-1.fc45",
            "weston-15.0.1-3.fc45",
            "gtk4-4.24.1-1.fc45",
            "libadwaita-1.10.0-2.fc45",
        ):
            with self.subTest(release_tag=release_tag):
                self.assertIn(release_tag, source)
        self.assertNotIn("--branch f45", source)

    def test_source_manifest_records_tag_and_git_commit(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("printf '%s\\t%s\\t%s\\n'", source)
        self.assertIn('git -C "$source_dir" rev-parse HEAD', source)

    def test_custom_cairo_is_installed_before_weston_and_gtk_builds(self):
        source = BUILDER.read_text(encoding="utf-8")
        install = source.index('mock -r "$MOCK_CONFIG" --install \\\n  "$cairo_runtime" "$cairo_devel"')
        weston = source.index("build_mock_package_preserving_root weston", install)
        gtk = source.index("build_mock_package_preserving_root gtk4", weston)
        self.assertLess(install, weston)
        self.assertLess(weston, gtk)

    def test_custom_gtk_is_installed_before_libadwaita_rebuild(self):
        source = BUILDER.read_text(encoding="utf-8")
        install = source.index('mock -r "$MOCK_CONFIG" --install "$gtk4_runtime" "$gtk4_devel"')
        rebuild = source.index("build_mock_package_preserving_root libadwaita", install)
        self.assertLess(install, rebuild)

    def test_development_rpms_are_separated_from_runtime_rpms(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn('mkdir -p "$OUTPUT_DIR/build-deps"', source)
        self.assertIn('"$OUTPUT_DIR/build-deps/"', source)
        self.assertIn("do not add these to the Live image", source)


if __name__ == "__main__":
    unittest.main()
