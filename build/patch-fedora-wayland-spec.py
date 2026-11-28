#!/usr/bin/env python3
"""Apply Fedora 45 Meson switches for Feclora's strict no-X11 graphics stack."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


EXPECTED = {
    "cairo": ("1.18.6", (
        "-Dxlib=disabled",
        "-Dxcb=disabled",
        "-Dxlib-xcb=disabled",
    )),
    "weston": ("15.0.1", (
        "-Dxwayland=false",
        "-Dbackend-x11=false",
        "-Dbackend-drm=true",
        "-Dshell-kiosk=true",
        "-Dsystemd=true",
        "-Drenderer-gl=false",
        "-Drenderer-vulkan=false",
    )),
    "gtk4": ("4.24.1", (
        "-Dx11-backend=false",
        "-Dwayland-backend=true",
        "-Dvulkan=disabled",
    )),
    "libadwaita": ("1.10.0", ()),
}

CAIRO_X11_DEPENDENCY_RE = re.compile(
    r"(?i)(?:\blibX11(?:-devel)?\b|\blibXext(?:-devel)?\b|"
    r"\blibXrender(?:-devel)?\b|\blibxcb(?:-devel)?\b|"
    r"pkgconfig\((?:x11|xext|xrender|xcb(?:-[a-z0-9-]+)?|cairo-xlib(?:-xrender)?|cairo-xcb(?:-shm)?)\)|"
    r"\bcairo-(?:xlib(?:-xrender)?|xcb(?:-shm)?)\.pc\b)"
)
CAIRO_X11_FILE_RE = re.compile(
    r"(?i)cairo-(?:xlib(?:-xrender)?|xcb(?:-shm)?)\.(?:h|pc)\b"
)
RPM_DEPENDENCY_TAG_RE = re.compile(
    r"^\s*(?:BuildRequires|Requires|Recommends|Suggests|Supplements|Enhances|Provides):"
)
RPM_SECTION_RE = re.compile(
    r"^%(?:prep|build|install|check|clean|files|package|description|"
    r"pre|post|preun|postun|trigger|filetrigger|changelog)(?:\s|$)"
)


def _strip_cairo_x11_entries(lines: list[str]) -> list[str]:
    """Remove Xlib/XCB package metadata and files from Cairo's split RPMs."""
    filtered: list[str] = []
    in_files_section = False
    for line in lines:
        if re.match(r"^%files(?:\s|$)", line):
            in_files_section = True
        elif RPM_SECTION_RE.match(line):
            in_files_section = False

        if RPM_DEPENDENCY_TAG_RE.match(line) and CAIRO_X11_DEPENDENCY_RE.search(line):
            continue
        if in_files_section and CAIRO_X11_FILE_RE.search(line):
            continue
        filtered.append(line)

    # Fail closed if Fedora changes the spec format and any X11 package or
    # payload declaration survives the targeted rewrite.
    in_files_section = False
    for line in filtered:
        if re.match(r"^%files(?:\s|$)", line):
            in_files_section = True
        elif RPM_SECTION_RE.match(line):
            in_files_section = False
        if RPM_DEPENDENCY_TAG_RE.match(line) and CAIRO_X11_DEPENDENCY_RE.search(line):
            raise ValueError(f"Cairo spec still advertises an X11 dependency: {line.strip()}")
        if in_files_section and CAIRO_X11_FILE_RE.search(line):
            raise ValueError(f"Cairo spec still packages an X11 file: {line.strip()}")
    return filtered


def patch_spec_text(package: str, source: str) -> str:
    if package not in EXPECTED:
        raise ValueError(f"unsupported Fedora package: {package}")
    expected_version, flags = EXPECTED[package]
    lines = source.splitlines()
    name_indexes = [i for i, line in enumerate(lines) if re.match(r"^Name:\s*", line)]
    epoch_indexes = [i for i, line in enumerate(lines) if re.match(r"^Epoch:\s*", line)]
    if len(name_indexes) != 1 or len(epoch_indexes) > 1:
        raise ValueError("spec must contain exactly one Name: field and at most one Epoch: field")
    spec_name = lines[name_indexes[0]].split(":", 1)[1].strip()
    if spec_name != package:
        raise ValueError(f"expected {package}.spec but found Name: {spec_name}")
    if epoch_indexes:
        lines[epoch_indexes[0]] = "Epoch:          1"
    else:
        lines.insert(name_indexes[0] + 1, "Epoch:          1")

    version_indexes = [i for i, line in enumerate(lines) if re.match(r"^Version:\s*", line)]
    release_indexes = [i for i, line in enumerate(lines) if re.match(r"^Release:\s*", line)]
    if len(version_indexes) != 1 or len(release_indexes) != 1:
        raise ValueError("spec must contain exactly one Version: and Release: field")
    version = lines[version_indexes[0]].split(":", 1)[1].strip()
    if version != expected_version:
        raise ValueError(f"{package} Fedora 45 source version must be {expected_version}, found {version}")
    lines[release_indexes[0]] = "Release:        99%{?dist}.feclora1"

    if flags:
        build_start = next((i for i, line in enumerate(lines) if line.strip() == "%build"), None)
        if build_start is None:
            raise ValueError("spec has no %build section")
        build_end = next(
            (i for i in range(build_start + 1, len(lines))
             if re.match(r"^%(install|check|files|package|description)(?:\s|$)", lines[i])),
            len(lines),
        )
        meson_indexes = [
            i for i in range(build_start + 1, build_end)
            if re.search(r"(?<![A-Za-z0-9_])%meson(?:\s|$)", lines[i])
        ]
        if not meson_indexes:
            raise ValueError("spec %build section has no %meson invocation to patch")
        for index in meson_indexes:
            line = lines[index].rstrip()
            continued = line.endswith("\\")
            if continued:
                line = line[:-1].rstrip()
            lines[index] = line + " " + " ".join(flags) + (" \\" if continued else "")

    if package == "cairo":
        lines = _strip_cairo_x11_entries(lines)

    result = "\n".join(lines) + "\n"
    for flag in flags:
        if flag not in result:
            raise ValueError(f"failed to inject required Meson option: {flag}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", choices=tuple(EXPECTED))
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    original = args.spec.read_text(encoding="utf-8")
    patched = patch_spec_text(args.package, original)
    args.spec.write_text(patched, encoding="utf-8")
    print(f"Patched Fedora 45 {args.package} spec: {args.spec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
