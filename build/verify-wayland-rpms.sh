#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
Usage:
  build/verify-wayland-rpms.sh [--installed-root ROOT] \
    weston.rpm weston-libs.rpm gtk4.rpm libadwaita.rpm cairo.rpm cairo-gobject.rpm [additional-rpms...]

Strictly audits every generated Fedora 45 Feclora binary subpackage from the
four pinned source RPM families. Rejects XWayland, Xorg, Openbox, Weston/GDK
X11 backends, Cairo Xlib/XCB surfaces, X11 typelibs, headers, pkg-config
metadata, libraries, packages, RPM requirements and advertised capabilities.
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
readonly X11_LIBRARY_FILE_RE='(^|/)(libX[^/]*\.(so(\.[^/]*)?|a|la)|libx11[^/]*\.(so(\.[^/]*)?|a|la)|libxcb[^/]*\.(so(\.[^/]*)?|a|la)|libxkbcommon-x11[^/]*\.(so(\.[^/]*)?|a|la)|libGLX[^/]*\.(so(\.[^/]*)?|a|la)|libxkbfile[^/]*\.(so(\.[^/]*)?|a|la)|libxshmfence[^/]*\.(so(\.[^/]*)?|a|la)|libfontenc[^/]*\.(so(\.[^/]*)?|a|la)|libICE[^/]*\.(so(\.[^/]*)?|a|la)|libSM[^/]*\.(so(\.[^/]*)?|a|la)|libgdk-x11[^/]*\.(so(\.[^/]*)?|a|la)|libcairo-(xlib|xcb)[^/]*\.(so(\.[^/]*)?|a|la))
readonly X11_HEADER_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)(backend-x11\.h|xwayland-api\.h|gdkx11[^/]*\.h|cairo-(xlib(-xrender)?|xcb(-shm)?)\.h|xkbcommon-x11\.h|glx[^/]*\.h)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)[^/]*(x11|xcb|xext|xrender|xinerama|xcursor|xfixes|xcomposite|xdamage|xrandr|xkbcommon-x11|xkbfile|glx|xwayland|gdk-x11|gtk4-x11|weston-x11)[^/]*\.pc$|(^|/)cairo-(xlib(-xrender)?|xcb(-shm)?)\.pc
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libx11[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xinerama|xcursor|xi|xfixes|xcomposite|xdamage|xrandr|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|xkbfile|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|libx11.*|libcairo-xlib.*|libcairo-xcb.*|xcb-util.*)

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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

readonly X11_HEADER_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)(backend-x11\.h|xwayland-api\.h|gdkx11[^/]*\.h|cairo-(xlib(-xrender)?|xcb(-shm)?)\.h|xkbcommon-x11\.h|glx[^/]*\.h)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)[^/]*(x11|xcb|xext|xrender|glx)[^/]*\.pc$|(^|/)cairo-(xlib(-xrender)?|xcb(-shm)?)\.pc$'
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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

readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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

readonly X11_HEADER_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)(backend-x11\.h|xwayland-api\.h|gdkx11[^/]*\.h|cairo-(xlib(-xrender)?|xcb(-shm)?)\.h|xkbcommon-x11\.h|glx[^/]*\.h)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)[^/]*(x11|xcb|xext|xrender|glx)[^/]*\.pc$|(^|/)cairo-(xlib(-xrender)?|xcb(-shm)?)\.pc$'
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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

readonly X11_HEADER_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)(backend-x11\.h|xwayland-api\.h|gdkx11[^/]*\.h|cairo-(xlib(-xrender)?|xcb(-shm)?)\.h|xkbcommon-x11\.h|glx[^/]*\.h)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)[^/]*(x11|xcb|xext|xrender|glx)[^/]*\.pc$|(^|/)cairo-(xlib(-xrender)?|xcb(-shm)?)\.pc$'
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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

readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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

readonly X11_HEADER_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)(backend-x11\.h|xwayland-api\.h|gdkx11[^/]*\.h|cairo-(xlib(-xrender)?|xcb(-shm)?)\.h|xkbcommon-x11\.h|glx[^/]*\.h)$'
readonly X11_METADATA_FILE_RE='(^|/)(X11|xcb|gdk/x11)/|(^|/)[^/]*(x11|xcb|xext|xrender|glx)[^/]*\.pc$|(^|/)cairo-(xlib(-xrender)?|xcb(-shm)?)\.pc$'
readonly X11_REQUIRE_RE='(^|[[:space:]])(libX[^[:space:]]*|libxcb[^[:space:]]*|libxkbcommon-x11[^[:space:]]*|libGLX[^[:space:]]*|libgdk-x11[^[:space:]]*|libxkbfile[^[:space:]]*|libxshmfence[^[:space:]]*|libfontenc[^[:space:]]*|libICE[^[:space:]]*|libSM[^[:space:]]*|libcairo-(xlib|xcb)[^[:space:]]*|xorg-x11-[^[:space:]]*|xwayland[^[:space:]]*|openbox[^[:space:]]*|xcb-util[^[:space:]]*|pkgconfig\((x11|x11-xcb|xext|xrender|xcb(-[^)]*)?|gdk-x11|gtk4-x11|xkbcommon-x11|glx|cairo-xlib(-xrender)?|cairo-xcb(-shm)?|weston-x11)\))([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-.*|xwayland.*|openbox.*|.*-x11.*|.*-xcb.*|.*-xwayland.*|cairo-xlib.*|cairo-xcb.*|.*-openbox.*|libX.*|libxcb.*|libxkbcommon-x11.*|libGLX.*|libgdk-x11.*|libxkbfile.*|libxshmfence.*|libfontenc.*|libICE.*|libSM.*|xcb-util.*)$'

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
    if grep -Eq "$pattern" <<<"$files"; then
      grep -E "$pattern" <<<"$files" >&2 || true
      fail "$origin contains a forbidden X11 backend, Openbox binary, library or development file."
    fi
  done
  if grep -Eq "$X11_REQUIRE_RE" <<<"$metadata"; then
    grep -E "$X11_REQUIRE_RE" <<<"$metadata" >&2 || true
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
  metadata="$(rpm -qp --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" || fail "Cannot read RPM metadata: $rpm_file"
  IFS='|' read -r epoch version release source_rpm <<<"$metadata"
  case "$source_rpm" in
    cairo-1.18.6-99.fc45.feclora1.src.rpm)
      expected_version="1.18.6"; source_prefix="cairo" ;;
    weston-15.0.1-99.fc45.feclora1.src.rpm)
      expected_version="15.0.1"; source_prefix="weston" ;;
    gtk4-4.24.1-99.fc45.feclora1.src.rpm)
      expected_version="4.24.1"; source_prefix="gtk4" ;;
    libadwaita-1.10.0-99.fc45.feclora1.src.rpm)
      expected_version="1.10.0"; source_prefix="libadwaita" ;;
    *) fail "$package_name has unexpected Fedora 45 Feclora source RPM provenance: $source_rpm." ;;
  esac
  [[ "$package_name" == "$source_prefix" || "$package_name" == "$source_prefix"-* ]] ||
    fail "$package_name does not belong to the $source_prefix source RPM family."
  [[ "$epoch" == 1 ]] || fail "$package_name must use Feclora graphics RPM epoch 1 (found $epoch)."
  [[ "$version" == "$expected_version" ]] || fail "$package_name must use Fedora 45 source version $expected_version (found $version)."
  [[ "$release" == 99.fc45.feclora1 ]] || fail "$package_name must carry the exact Feclora rebuild release 99.fc45.feclora1 (found $release)."
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
  check_installed_custom() {
    local package="$1" expected_version="$2" expected_source="$3" metadata epoch version release source
    metadata="$(rpm --root "$installed_root" -q --qf '%{EPOCH}|%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$package")" ||
      fail "Cannot query installed custom package provenance: $package"
    IFS='|' read -r epoch version release source <<<"$metadata"
    [[ "$epoch" == 1 && "$version" == "$expected_version" && "$release" == "99.fc45.feclora1" && "$source" == "$expected_source" ]] ||
      fail "Installed $package is not the audited Fedora 45 Feclora rebuild (found $metadata)."
  }
  check_installed_custom weston 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom weston-libs 15.0.1 weston-15.0.1-99.fc45.feclora1.src.rpm
  check_installed_custom gtk4 4.24.1 gtk4-4.24.1-99.fc45.feclora1.src.rpm
  check_installed_custom libadwaita 1.10.0 libadwaita-1.10.0-99.fc45.feclora1.src.rpm
  check_installed_custom cairo 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  check_installed_custom cairo-gobject 1.18.6 cairo-1.18.6-99.fc45.feclora1.src.rpm
  for required in python3-gobject python3-cairo; do
    python_release="$(rpm --root "$installed_root" -q --qf '%{RELEASE}\n' "$required")" ||
      fail "Cannot query Fedora system Python binding package: $required"
    [[ "$python_release" == *".fc45"* ]] ||
      fail "$required must come from Fedora 45 system repositories (found release $python_release)."
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
