#!/usr/bin/env python3
"""Apply the Fedora 45 Meson switches required for Feclora's strict no-X11 builds."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


EXPECTED = {
    "weston": ("15.0.1", (
        "-Dxwayland=false",
        "-Dbackend-x11=false",
        "-Dbackend-drm=true",
        "-Dshell-kiosk=true",
    )),
    "gtk4": ("4.24.1", (
        "-Dx11-backend=false",
        "-Dwayland-backend=true",
    )),
    "libadwaita": ("1.10.0", ()),
}


def patch_spec_text(package: str, source: str) -> str:
    if package not in EXPECTED:
        raise ValueError(f"unsupported Fedora package: {package}")
    expected_version, flags = EXPECTED[package]
    lines = source.splitlines()
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

        result = "\n".join(lines) + "\n"
        for flag in flags:
            if flag not in result:
                raise ValueError(f"failed to inject required Meson option: {flag}")
        return result

    return "\n".join(lines) + "\n"


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
