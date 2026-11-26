#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
Usage:
  build/verify-wayland-rpms.sh [--installed-root ROOT] weston.rpm weston-libs.rpm gtk4.rpm libadwaita.rpm [additional-rpms...]

Checks the four required Fedora-matched runtime RPMs and every additional RPM
supplied (for example gtk4-devel used to rebuild libadwaita).
With --installed-root, also audits the complete installed RPM database and file
payload under ROOT for X11 libraries, backends, compatibility servers and WMs.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

installed_root=""
rpm_files=()
while (($#)); do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --installed-root)
      (($# >= 2)) || fail "--installed-root requires a path."
      installed_root="$2"
      shift 2
      ;;
    --)
      shift
      rpm_files+=("$@")
      break
      ;;
    -*)
      fail "Unknown option: $1"
      ;;
    *)
      rpm_files+=("$1")
      shift
      ;;
  esac
done

(("${#rpm_files[@]}" >= 4)) ||
  fail "Supply the four required RPMs: weston, weston-libs, gtk4 and libadwaita."
command -v rpm >/dev/null 2>&1 || fail "The rpm command is required."
if [[ -n "$installed_root" && ! -d "$installed_root" ]]; then
  fail "Installed root does not exist: $installed_root"
fi

readonly X11_FILE_RE='(^|/)(Xwayland|Xorg|openbox|xwayland\.so|x11-backend\.so|GdkX11-4\.0\.(typelib|gir)|gdk/x11/|libgdk-x11-[^/]*\.so([.0-9]*)?|libX11(-xcb)?\.so([.0-9]*)?|libXcursor\.so([.0-9]*)?|libXdamage\.so([.0-9]*)?|libXext\.so([.0-9]*)?|libXfixes\.so([.0-9]*)?|libXi\.so([.0-9]*)?|libXinerama\.so([.0-9]*)?|libXrandr\.so([.0-9]*)?|libXcomposite\.so([.0-9]*)?|libXrender\.so([.0-9]*)?|libXau\.so([.0-9]*)?|libXdmcp\.so([.0-9]*)?|libICE\.so([.0-9]*)?|libSM\.so([.0-9]*)?|libXtst\.so([.0-9]*)?|libXxf86vm\.so([.0-9]*)?|libxcb\.so([.0-9]*)?|gtk4-x11\.pc|gdk4-x11\.pc)$'
readonly X11_REQUIRE_RE='(^|[^[:alnum:]_])(libX11(-xcb)?|libXcursor|libXdamage|libXext|libXfixes|libXi|libXinerama|libXrandr|libXcomposite|libXrender|libXau|libXdmcp|libICE|libSM|libXtst|libXxf86vm|libxcb)(\.so|[[:space:]]|$)|pkgconfig\((x11|xcb)\)|(^|[[:space:]])(xorg-x11-server-Xwayland|xorg-x11-server-Xorg|xwayland|openbox)([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland$|openbox$|libX11(-xcb)?(-devel)?$|libXcursor(-devel)?$|libXdamage(-devel)?$|libXext(-devel)?$|libXfixes(-devel)?$|libXi(-devel)?$|libXinerama(-devel)?$|libXrandr(-devel)?$|libXcomposite(-devel)?$|libXrender(-devel)?$|libXau(-devel)?$|libXdmcp(-devel)?$|libICE(-devel)?$|libSM(-devel)?$|libXtst(-devel)?$|libXxf86vm(-devel)?$|libxcb(-devel)?$)'

check_payload() {
  local origin="$1" files="$2" requirements="$3"
  if grep -Eiq "$X11_FILE_RE" <<<"$files"; then
    grep -Ei "$X11_FILE_RE" <<<"$files" >&2 || true
    fail "$origin contains an X11/XWayland backend or library file."
  fi
  if grep -Eiq "$X11_REQUIRE_RE" <<<"$requirements"; then
    grep -Ei "$X11_REQUIRE_RE" <<<"$requirements" >&2 || true
    fail "$origin has an X11/XWayland runtime or build dependency."
  fi
}

declare -A seen=()
for rpm_file in "${rpm_files[@]}"; do
  [[ -s "$rpm_file" ]] || fail "RPM file is missing or empty: $rpm_file"
  package_name="$(rpm -qp --qf '%{NAME}\n' "$rpm_file")" ||
    fail "Cannot read RPM metadata: $rpm_file"
  if [[ "$package_name" =~ $BAD_PACKAGE_RE ]]; then
    fail "Forbidden X11 package supplied for admission: $package_name"
  fi
  case "$package_name" in
    weston|weston-libs|weston-devel) expected_version="15.0.1" ;;
    gtk4|gtk4-devel) expected_version="4.24.1" ;;
    libadwaita|libadwaita-devel) expected_version="1.10.0" ;;
    *) fail "Unexpected RPM package '$package_name' in $rpm_file." ;;
  esac
  metadata="$(rpm -qp --qf '%{VERSION}|%{RELEASE}|%{SOURCERPM}\\n' "$rpm_file")" ||
    fail "Cannot read Fedora source metadata: $rpm_file"
  IFS='|' read -r version release source_rpm <<<"$metadata"
  [[ "$version" == "$expected_version" ]] ||
    fail "$package_name must be built from version $expected_version; found $version."
  [[ "$release" == *fc45* && "$source_rpm" == *fc45.src.rpm ]] ||
    fail "$package_name must retain Fedora 45 release and source-RPM provenance."
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
  installed_listing="$(rpm --root "$installed_root" -qa --qf '%{NAME}\n')" ||
    fail "Cannot query installed RPM database under $installed_root."
  mapfile -t installed_packages <<<"$installed_listing"
  (("${#installed_packages[@]}" > 0)) || fail "No installed RPM database found under $installed_root."
  for required in weston weston-libs gtk4 libadwaita; do
    grep -Fxq "$required" <<<"$installed_listing" ||
      fail "Required Wayland runtime package is not installed under $installed_root: $required"
  done
  for package_name in "${installed_packages[@]}"; do
    if [[ "$package_name" =~ $BAD_PACKAGE_RE ]]; then
      fail "Forbidden X11 package is installed in the target root: $package_name"
    fi
    files="$(rpm --root "$installed_root" -ql "$package_name")" ||
      fail "Cannot list installed files for package $package_name."
    requirements="$(rpm --root "$installed_root" -q --requires "$package_name")" ||
      fail "Cannot list installed requirements for package $package_name."
    check_payload "installed package $package_name" "$files" "$requirements"
  done
fi

printf 'Wayland-only RPM audit passed for: weston, weston-libs, gtk4 and libadwaita.\n'
if [[ -n "$installed_root" ]]; then
  printf 'Installed-root audit passed: %s (%d RPM packages).\n' "$installed_root" "${#installed_packages[@]}"
fi
