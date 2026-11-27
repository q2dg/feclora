#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
Usage:
  build/verify-wayland-rpms.sh [--installed-root ROOT] weston.rpm weston-libs.rpm gtk4.rpm libadwaita.rpm [additional-rpms...]

Strictly audits the Fedora 45 Feclora Wayland-only rebuilds. Rejects XWayland,
Xorg, Weston/GDK X11 backends, X11 typelibs, X11 development metadata,
libraries, packages and RPM dependencies. Optional development RPMs are
subject to the same policy. --installed-root audits every installed RPM.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

installed_root=""
rpm_files=()
while (($#)); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --installed-root)
      (($# >= 2)) || fail "--installed-root requires a path."
      installed_root="$2"; shift 2 ;;
    --)
      shift; rpm_files+=("$@"); break ;;
    -*)
      fail "Unknown option: $1" ;;
    *)
      rpm_files+=("$1"); shift ;;
  esac
done

(("${#rpm_files[@]}" >= 4)) || fail "Supply weston, weston-libs, gtk4 and libadwaita RPMs."
command -v rpm >/dev/null 2>&1 || fail "The rpm command is required."
if [[ -n "$installed_root" && ! -d "$installed_root" ]]; then
  fail "Installed root does not exist: $installed_root"
fi

readonly X11_BACKEND_FILE_RE='(^|/)(xwayland\.so|x11-backend\.so|GdkX11-4\.0\.typelib)$'
readonly X11_LIBRARY_FILE_RE='(^|/)(libX[^/]*\.so(\.[^/]*)?|libxcb[^/]*\.so(\.[^/]*)?|libxkbfile[^/]*\.so(\.[^/]*)?|libxshmfence[^/]*\.so(\.[^/]*)?|libfontenc[^/]*\.so(\.[^/]*)?|libICE[^/]*\.so(\.[^/]*)?|libSM[^/]*\.so(\.[^/]*)?)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb)/|(^|/)(x11|xcb|gdkx11)\.pc$'
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|xorg-x11-[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|xcb|gdk-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|libX.*|libxcb.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

check_package_name() {
  local package="$1"
  if [[ "$package" =~ $BAD_PACKAGE_RE ]]; then
    fail "Forbidden X11 package is present: $package"
  fi
}

check_payload() {
  local origin="$1" files="$2" requirements="$3"
  local match
  for pattern in "$X11_BACKEND_FILE_RE" "$X11_LIBRARY_FILE_RE" "$X11_METADATA_FILE_RE"; do
    if grep -Eiq "$pattern" <<<"$files"; then
      grep -Ei "$pattern" <<<"$files" >&2 || true
      fail "$origin contains forbidden X11 backend, typelib, library or development metadata."
    fi
  done
  if grep -Eiq "$X11_REQUIRE_RE" <<<"$requirements"; then
    grep -Eiq "$X11_REQUIRE_RE" <<<"$requirements" && grep -Ei "$X11_REQUIRE_RE" <<<"$requirements" >&2 || true
    fail "$origin has an X11 runtime or build dependency."
  fi
}

declare -A seen=()
for rpm_file in "${rpm_files[@]}"; do
  [[ -s "$rpm_file" ]] || fail "RPM file is missing or empty: $rpm_file"
  package_name="$(rpm -qp --qf '%{NAME}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  check_package_name "$package_name"
  case "$package_name" in
    weston|weston-libs|gtk4|libadwaita|weston-devel|gtk4-devel|libadwaita-devel) ;;
    *) fail "Unexpected RPM package '$package_name' in $rpm_file." ;;
  esac

  metadata="$(rpm -qp --qf '%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read Fedora source metadata: $rpm_file"
  IFS='|' read -r version release source_rpm <<<"$metadata"
  case "$package_name" in
    weston|weston-libs|weston-devel) expected_version="15.0.1" ;;
    gtk4|gtk4-devel) expected_version="4.24.1" ;;
    libadwaita|libadwaita-devel) expected_version="1.10.0" ;;
  esac
  [[ "$version" == "$expected_version" ]] || fail "$package_name must be built from Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == *fc45* && "$release" == *feclora* ]] || fail "$package_name must carry an fc45 Feclora rebuild release (found $release)."
  [[ "$source_rpm" == *fc45*.src.rpm ]] || fail "$package_name must retain Fedora 45 source-RPM provenance (found $source_rpm)."
  [[ -z "${seen[$package_name]+x}" ]] || fail "Duplicate RPM package: $package_name"
  seen[$package_name]=1

  files="$(rpm -qpl "$rpm_file")" || fail "Cannot list payload files: $rpm_file"
  requirements="$(rpm -qpR "$rpm_file")" || fail "Cannot list RPM requirements: $rpm_file"
  check_payload "$package_name ($rpm_file)" "$files" "$requirements"
done

for required in weston weston-libs gtk4 libadwaita; do
  [[ -n "${seen[$required]+x}" ]] || fail "Required RPM package is missing: $required"
done

if [[ -n "$installed_root" ]]; then
  installed_listing="$(rpm --root "$installed_root" -qa --qf '%{NAME}\n')" || fail "Cannot query installed RPM database under $installed_root."
  mapfile -t installed_packages <<<"$installed_listing"
  (("${#installed_packages[@]}" > 0)) || fail "No installed RPM database found under $installed_root."
  for required in weston weston-libs gtk4 libadwaita; do
    grep -Fxq "$required" <<<"$installed_listing" || fail "Required Wayland runtime package is not installed under $installed_root: $required"
  done
  for package_name in "${installed_packages[@]}"; do
    check_package_name "$package_name"
    files="$(rpm --root "$installed_root" -ql "$package_name")" || fail "Cannot list installed files for $package_name."
    requirements="$(rpm --root "$installed_root" -q --requires "$package_name")" || fail "Cannot list installed requirements for $package_name."
    check_payload "installed package $package_name" "$files" "$requirements"
  done
fi

printf 'Strict X11-free Fedora 45 Feclora RPM audit passed for Weston 15.0.1, GTK 4.24.1 and libadwaita 1.10.0.\n'
if [[ -n "$installed_root" ]]; then
  printf 'Installed-root X11 audit passed: %s (%d RPM packages).\n' "$installed_root" "${#installed_packages[@]}"
fi
