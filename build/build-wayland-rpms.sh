#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MOCK_CONFIG="${FECLORA_MOCK_CONFIG:-fedora-45-x86_64}"
OUTPUT_DIR="${FECLORA_WAYLAND_RPM_DIR:-$ROOT_DIR/out/wayland-rpms}"
WORK_PARENT="${FECLORA_WAYLAND_WORK_PARENT:-$ROOT_DIR/out}"
PATCHER="$ROOT_DIR/build/patch-fedora-wayland-spec.py"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -eq 0 ]]; then
  fail "Run Mock as an unprivileged user in the mock group, not as root."
fi
[[ -s "$PATCHER" ]] || fail "Fedora spec patcher is missing."
for command in git fedpkg mock rpmbuild rpm python3; do
  command -v "$command" >/dev/null 2>&1 || fail "Required build command is missing: $command"
done

# This build must use Fedora 45's package branches and Mock root.
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == fedora && "${VERSION_ID:-}" == 45 ]] ||
  fail "Build the custom RPMs on a Fedora 45 host; detected ${PRETTY_NAME:-unknown}."
id -nG | tr ' ' '\n' | grep -Fxq mock ||
  fail "The current user must be in the mock group (log out/in after adding it)."
[[ -f "/etc/mock/${MOCK_CONFIG}.cfg" ]] ||
  fail "Mock configuration /etc/mock/${MOCK_CONFIG}.cfg is missing."

[[ ! -e "$OUTPUT_DIR" ]] || fail "Output directory already exists; move it aside first: $OUTPUT_DIR"
mkdir -p "$WORK_PARENT"
WORK_DIR="$(mktemp -d "$WORK_PARENT/.feclora-wayland-rpms.XXXXXX")"
RESULTS="$WORK_DIR/results"
mkdir -p "$RESULTS"
trap 'rm -rf -- "$WORK_DIR"' EXIT

prepare_fedora_srpm() {
  local package="$1" source_ref="$2" source_dir="$WORK_DIR/$package" top="$WORK_DIR/rpmbuild-$package"
  local spec_file srpm
  [[ "$source_ref" == "${package}-"* ]] || fail "Invalid Fedora dist-git release tag for $package: $source_ref"
  git clone --depth 1 --branch "$source_ref" "https://src.fedoraproject.org/rpms/${package}.git" "$source_dir" >&2
  printf '%s\t%s\t%s\n' "$package" "$source_ref" "$(git -C "$source_dir" rev-parse HEAD)" >> "$WORK_DIR/source-commits.tsv"
  (
    cd "$source_dir"
    fedpkg sources >&2
  )
  spec_file="$source_dir/$package.spec"
  [[ -s "$spec_file" ]] || fail "Fedora f45 dist-git did not provide $package.spec."
  python3 "$PATCHER" "$package" "$spec_file" >&2

  mkdir -p "$top/SOURCES" "$top/SPECS" "$top/SRPMS"
  cp "$spec_file" "$top/SPECS/$package.spec"
  find "$source_dir" -maxdepth 1 -type f \
    ! -name "$package.spec" ! -name sources ! -name .gitignore \
    -exec cp -t "$top/SOURCES" -- {} +
  rpmbuild -bs \
    --define "_topdir $top" \
    --define "dist .fc45" \
    "$top/SPECS/$package.spec" >&2
  mapfile -t srpms < <(find "$top/SRPMS" -type f -name '*.src.rpm' -print)
  (("${#srpms[@]}" == 1)) || fail "Expected exactly one Fedora 45 $package SRPM."
  srpm="${srpms[0]}"
  printf '%s\n' "$srpm"
}

build_mock_package() {
  local package="$1" srpm="$2" result_dir="$RESULTS/$package"
  mkdir -p "$result_dir"
  mock -r "$MOCK_CONFIG" --rebuild --resultdir="$result_dir" "$srpm"
}

build_mock_package_preserving_root() {
  local package="$1" srpm="$2" result_dir="$RESULTS/$package"
  mkdir -p "$result_dir"
  mock -r "$MOCK_CONFIG" --rebuild --no-clean --resultdir="$result_dir" "$srpm"
}

find_binary_rpm() {
  local result_dir="$1" package="$2" candidate
  local -a matches=()
  while IFS= read -r candidate; do
    [[ "$(rpm -qp --qf '%{NAME}' "$candidate")" == "$package" ]] && matches+=("$candidate")
  done < <(find "$result_dir" -maxdepth 1 -type f -name '*.rpm' ! -name '*.src.rpm' ! -name '*debuginfo*' -print)
  (("${#matches[@]}" == 1)) || fail "Expected one $package binary RPM in $result_dir; found ${#matches[@]}."
  printf '%s\n' "${matches[0]}"
}

printf '[1/6] Fetching and building Fedora 45 Cairo 1.18.6 without Xlib/XCB...\n'
cairo_srpm="$(prepare_fedora_srpm cairo cairo-1.18.6-1.fc45)"
build_mock_package cairo "$cairo_srpm"
cairo_runtime="$(find_binary_rpm "$RESULTS/cairo" cairo)"
cairo_devel="$(find_binary_rpm "$RESULTS/cairo" cairo-devel)"
cairo_gobject="$(find_binary_rpm "$RESULTS/cairo" cairo-gobject)"
cairo_gobject_devel="$(find_binary_rpm "$RESULTS/cairo" cairo-gobject-devel)"

printf '[2/6] Initializing Mock with the X11-free Cairo runtime/development stack...\n'
mock -r "$MOCK_CONFIG" --init
mock -r "$MOCK_CONFIG" --install \
  "$cairo_runtime" "$cairo_devel" "$cairo_gobject" "$cairo_gobject_devel"

printf '[3/6] Fetching and building Fedora 45 Weston 15.0.1 without XWayland/X11...\n'
weston_srpm="$(prepare_fedora_srpm weston weston-15.0.1-3.fc45)"
build_mock_package_preserving_root weston "$weston_srpm"

printf '[4/6] Building Fedora 45 GTK 4.24.1 with native Wayland only...\n'
gtk4_srpm="$(prepare_fedora_srpm gtk4 gtk4-4.24.1-1.fc45)"
build_mock_package_preserving_root gtk4 "$gtk4_srpm"
gtk4_runtime="$(find_binary_rpm "$RESULTS/gtk4" gtk4)"
gtk4_devel="$(find_binary_rpm "$RESULTS/gtk4" gtk4-devel)"
mock -r "$MOCK_CONFIG" --install "$gtk4_runtime" "$gtk4_devel"

printf '[5/6] Rebuilding Fedora 45 libadwaita 1.10.0 against custom GTK4/Cairo...\n'
libadwaita_srpm="$(prepare_fedora_srpm libadwaita libadwaita-1.10.0-2.fc45)"
build_mock_package_preserving_root libadwaita "$libadwaita_srpm"
libadwaita_rpm="$(find_binary_rpm "$RESULTS/libadwaita" libadwaita)"

printf '[6/6] Auditing the actual binary RPM payloads, dependencies and capabilities...\n'
weston_rpm="$(find_binary_rpm "$RESULTS/weston" weston)"
weston_libs_rpm="$(find_binary_rpm "$RESULTS/weston" weston-libs)"
cairo_rpms=("$cairo_runtime" "$cairo_gobject")
build_dependency_rpms=("$cairo_devel" "$cairo_gobject_devel" "$gtk4_devel")
bash "$ROOT_DIR/build/verify-wayland-rpms.sh" \
  "$weston_rpm" "$weston_libs_rpm" "$gtk4_runtime" "$libadwaita_rpm" \
  "${cairo_rpms[@]}" "${build_dependency_rpms[@]}"

mkdir -p "$OUTPUT_DIR/build-deps"
cp "$weston_rpm" "$weston_libs_rpm" "$gtk4_runtime" "$libadwaita_rpm" "${cairo_rpms[@]}" "$OUTPUT_DIR/"
cp "${build_dependency_rpms[@]}" "$OUTPUT_DIR/build-deps/"
cp "$WORK_DIR/source-commits.tsv" "$OUTPUT_DIR/"
rpm -qp --qf '%{NAME} %{EPOCH}:%{VERSION}-%{RELEASE} source=%{SOURCERPM}\n' \
  "$OUTPUT_DIR"/*.rpm "$OUTPUT_DIR"/build-deps/*.rpm
printf 'Strictly audited runtime RPMs copied to %s\n' "$OUTPUT_DIR"
printf 'Build-only development RPMs copied to %s/build-deps (do not add these to the Live image).\n' "$OUTPUT_DIR"
printf 'The Live Kickstart has not been changed to install or enable these RPMs.\n'
