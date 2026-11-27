#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
Usage:
  build/verify-wayland-rpms.sh [--installed-root ROOT] \
    weston.rpm weston-libs.rpm gtk4.rpm libadwaita.rpm cairo.rpm cairo-gobject.rpm [additional-rpms...]

Strictly audits Fedora 45 Feclora Wayland-only rebuilds. Rejects XWayland,
Xorg, Openbox, Weston/GDK X11 backends, Cairo Xlib/XCB surfaces, X11 typelibs,
headers, pkg-config metadata, libraries, packages, RPM requirements and
advertised capabilities. Optional development RPMs receive the same audit.
--installed-root audits every installed RPM in a completed target root.
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

rpm_count=0
for _rpm_file in "${rpm_files[@]}"; do
  ((rpm_count += 1))
done
((rpm_count >= 6)) || fail "Supply Weston, GTK4, libadwaita, Cairo and Cairo-GObject runtime RPMs."
command -v rpm >/dev/null 2>&1 || fail "The rpm command is required."
if [[ -n "$installed_root" && ! -d "$installed_root" ]]; then
  fail "Installed root does not exist: $installed_root"
fi

readonly X11_BACKEND_FILE_RE='(^|/)(xwayland(\.so)?|weston-xwayland|Xwayland|Xorg|x11-backend\.so|backend-x11\.h|xwayland-api\.h|GdkX11-4\.0\.(typelib|gir)|openbox|openbox-session|cairo-(xlib(-xrender)?|xcb(-shm)?)\.(h|pc))$'
readonly X11_LIBRARY_FILE_RE='(^|/)(libX[^/]*\.so(\.[^/]*)?|libxcb[^/]*\.so(\.[^/]*)?|libxkbcommon-x11[^/]*\.so(\.[^/]*)?|libGLX[^/]*\.so(\.[^/]*)?|libxkbfile[^/]*\.so(\.[^/]*)?|libxshmfence[^/]*\.so(\.[^/]*)?|libfontenc[^/]*\.so(\.[^/]*)?|libICE[^/]*\.so(\.[^/]*)?|libSM[^/]*\.so(\.[^/]*)?|libgdk-x11[^/]*\.so(\.[^/]*)?|libcairo-(xlib|xcb)[^/]*\.so(\.[^/]*)?)$'
readonly X11_HEADER_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)(backend-x11\.h|xwayland-api\.h|gdkx11[^/]*\.h|cairo-(xlib(-xrender)?|xcb(-shm)?)\.h|xkbcommon-x11\.h|glx[^/]*\.h)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)[^/]*(x11|xcb|xext|xrender|glx)[^/]*\.pc$|(^|/)cairo-(xlib(-xrender)?|xcb(-shm)?)\.pc$'
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

check_package_name() {
  local package="$1"
  if [[ "$package" =~ $BAD_PACKAGE_RE ]]; then
    fail "Forbidden X11 package or Openbox package is present: $package"
  fi
}

check_payload() {
  local origin="$1" files="$2" metadata="$3"
  local pattern
  for pattern in "$X11_BACKEND_FILE_RE" "$X11_LIBRARY_FILE_RE" "$X11_HEADER_FILE_RE" "$X11_METADATA_FILE_RE"; do
    if grep -Eiq "$pattern" <<<"$files"; then
      grep -Ei "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eiq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -Ei "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
    fail "$origin has an X11 requirement or advertises an X11 capability."
  fi
}

rpm_metadata() {
  local rpm_file="$1" option output metadata=""
  for option in --requires --provides --recommends --suggests --supplements --enhances; do
    output="$(rpm -qp "$option" "$rpm_file")" || fail "Cannot read $option metadata: $rpm_file"
    metadata+=$'\n'"$output"
  done
  printf '%s' "$metadata"
}

declare -A seen=()
libseat_launcher_seen=0
for rpm_file in "${rpm_files[@]}"; do
  [[ -s "$rpm_file" ]] || fail "RPM file is missing or empty: $rpm_file"
  package_name="$(rpm -qp --qf '%{NAME}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  check_package_name "$package_name"
  case "$package_name" in
    cairo|cairo-gobject|cairo-devel|cairo-gobject-devel|weston|weston-libs|gtk4|libadwaita|weston-devel|gtk4-devel|libadwaita-devel) ;;
    *) fail "Unexpected RPM package '$package_name' in $rpm_file." ;;
  esac

  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$package_name" in
    cairo|cairo-gobject|cairo-devel|cairo-gobject-devel) expected_version="1.18.6" ;;
    weston|weston-libs|weston-devel) expected_version="15.0.1" ;;
    gtk4|gtk4-devel) expected_version="4.24.1" ;;
    libadwaita|libadwaita-devel) expected_version="1.10.0" ;;
  esac
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora* ]] || fail "$package_name must carry the reserved 99.fc45.feclora rebuild release (found $release)."
  [[ "$source_rpm" == *fc45*.src.rpm ]] || fail "$package_name must retain Fedora 45 source-RPM provenance (found $source_rpm)."
  [[ -z "${seen[$package_name]+x}" ]] || fail "Duplicate RPM package: $package_name"
  seen[$package_name]=1

  files="$(rpm -qpl "$rpm_file")" || fail "Cannot list payload files: $rpm_file"
  package_metadata="$(rpm_metadata "$rpm_file")"
  check_payload "$package_name ($rpm_file)" "$files" "$package_metadata"
  if [[ "$package_name" == weston-libs ]] &&
    grep -Eiq '(^|[[:space:]])libseat\.so([.[:space:]]|$)' <<<"$package_metadata"; then
    libseat_launcher_seen=1
  fi
done

[[ "$libseat_launcher_seen" == 1 ]] ||
  fail "Weston libseat launcher support is missing: weston-libs does not require libseat."

for required in weston weston-libs gtk4 libadwaita cairo cairo-gobject; do
  [[ -n "${seen[$required]+x}" ]] || fail "Required RPM package is missing: $required"
done

if [[ -n "$installed_root" ]]; then
  installed_listing="$(rpm --root "$installed_root" -qa --qf '%{NAME}\n')" || fail "Cannot query installed RPM database under $installed_root."
  mapfile -t installed_packages <<<"$installed_listing"
  installed_count=0
  for _package in "${installed_packages[@]}"; do
    ((installed_count += 1))
  done
  ((installed_count > 0)) || fail "No installed RPM database found under $installed_root."
  for required in weston weston-libs gtk4 libadwaita cairo cairo-gobject python3-gobject python3-cairo; do
    grep -Fxq "$required" <<<"$installed_listing" || fail "Required Wayland runtime package is not installed under $installed_root: $required"
  done
  for package_name in "${installed_packages[@]}"; do
    check_package_name "$package_name"
    files="$(rpm --root "$installed_root" -ql "$package_name")" || fail "Cannot list installed files for $package_name."
    package_metadata=""
    for option in --requires --provides --recommends --suggests --supplements --enhances; do
      output="$(rpm --root "$installed_root" -q "$option" "$package_name")" || fail "Cannot read installed $option metadata for $package_name."
      package_metadata+=$'\n'"$output"
    done
    check_payload "installed package $package_name" "$files" "$package_metadata"
  done
fi

printf 'Strict X11-free Fedora 45 RPM audit passed for Weston 15.0.1, GTK 4.24.1, libadwaita 1.10.0 and Cairo 1.18.6; Openbox was also excluded.\n'
if [[ -n "$installed_root" ]]; then
  printf 'Installed-root X11 audit passed (Openbox excluded): %s (%d RPM packages).\n' "$installed_root" "$installed_count"
fi
