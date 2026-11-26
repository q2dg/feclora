#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

usage() {
  cat <<'EOF'
Usage:
  build/verify-wayland-rpms.sh [--installed-root ROOT] weston.rpm weston-libs.rpm gtk4.rpm libadwaita.rpm [additional-rpms...]

Checks Fedora 45 runtime RPM provenance and rejects Xorg/XWayland server
executables or server packages. Optional X11 client backends and libraries in
official Fedora builds are allowed: the appliance policy is not to run an X
server, not to strip every unused compatibility interface from GTK or Weston.
With --installed-root, audits the complete installed RPM database and payload.
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

readonly XSERVER_FILE_RE='(^|/)(Xwayland|Xorg)$'
readonly XSERVER_REQUIRE_RE='(^|[[:space:]])(xorg-x11-server-Xwayland|xorg-x11-server-Xorg|xwayland)([[:space:]]|$)'
readonly BAD_PACKAGE_RE='^(xorg-x11-server-Xwayland|xorg-x11-server-Xorg|xwayland)$'

check_payload() {
  local origin="$1" files="$2" requirements="$3"
  if grep -Eiq "$XSERVER_FILE_RE" <<<"$files"; then
    grep -Ei "$XSERVER_FILE_RE" <<<"$files" >&2 || true
    fail "$origin contains an Xorg/XWayland server executable."
  fi
  if grep -Eiq "$XSERVER_REQUIRE_RE" <<<"$requirements"; then
    grep -Ei "$XSERVER_REQUIRE_RE" <<<"$requirements" >&2 || true
    fail "$origin depends on an Xorg/XWayland server package."
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
    weston|weston-libs|gtk4|libadwaita|weston-devel|gtk4-devel|libadwaita-devel) ;;
    *) fail "Unexpected RPM package '$package_name' in $rpm_file." ;;
  esac
  metadata="$(rpm -qp --qf '%{VERSION}|%{RELEASE}|%{SOURCERPM}\n' "$rpm_file")" ||
    fail "Cannot read Fedora source metadata: $rpm_file"
  IFS='|' read -r version release source_rpm <<<"$metadata"
  [[ -n "$version" ]] || fail "$package_name has no RPM version metadata."
  [[ "$release" == *fc45* && "$source_rpm" == *fc45*.src.rpm ]] ||
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

printf 'Wayland kiosk RPM audit passed for Fedora 45: weston, weston-libs, gtk4 and libadwaita.\n'
if [[ -n "$installed_root" ]]; then
  printf 'Installed-root audit passed: %s (%d RPM packages).\n' "$installed_root" "${#installed_packages[@]}"
fi
