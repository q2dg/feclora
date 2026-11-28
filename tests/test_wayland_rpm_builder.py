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

    def test_preserving_builds_disable_both_prebuild_and_postbuild_cleanup(self):
        source = BUILDER.read_text(encoding="utf-8")
        function = source[source.index("build_mock_package_preserving_root()"):source.index("find_binary_rpm()")]
        self.assertIn("--no-clean", function)
        self.assertIn("--no-cleanup-after", function)

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

    def test_runtime_closure_is_resolved_and_audited_before_output_copy(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("RUNTIME_MOCK_CONFIG=", source)
        self.assertIn("config_opts['chroot_setup_cmd'] = 'install bash coreutils rpm dnf5'", source)
        self.assertIn('"${runtime_rpms[@]}" python3-gobject python3-cairo', source)
        self.assertIn('--installed-root "$runtime_root"', source)
        self.assertIn('rpm --root "$runtime_root" -qa', source)
        self.assertIn('"$WORK_DIR/runtime-closure.txt" "$OUTPUT_DIR/"', source)
        self.assertLess(source.index('--installed-root "$runtime_root"'),
                        source.index('mkdir -p "$OUTPUT_DIR/build-deps"'))

    def test_audits_all_generated_binary_rpms_before_copying_runtime_subset(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("find \"$RESULTS\" -mindepth 2 -maxdepth 2 -type f -name '*.rpm' ! -name '*.src.rpm'", source)
        self.assertIn('bash "$ROOT_DIR/build/verify-wayland-rpms.sh" "${audit_rpms[@]}"', source)
        self.assertIn('runtime_rpm_paths["$rpm_file"]=1', source)
        self.assertIn("*-debuginfo|*-debugsource", source)

    def test_preserves_mock_logs_and_patched_source_rpms(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertIn("trap cleanup EXIT", source)
        self.assertIn("preserving workspace and Mock logs", source)
        self.assertIn('mkdir -p "$OUTPUT_DIR/build-deps" "$OUTPUT_DIR/build-logs" "$OUTPUT_DIR/sources"', source)
        self.assertIn('cp "$cairo_srpm" "$weston_srpm" "$gtk4_srpm" "$libadwaita_srpm" "$OUTPUT_DIR/sources/"', source)
        self.assertIn('> "$OUTPUT_DIR/build-environment.txt"', source)


if __name__ == "__main__":
    unittest.main()
