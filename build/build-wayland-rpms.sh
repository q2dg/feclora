#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "\${BASH_SOURCE[0]}")/.." && pwd)"
MOCK_CONFIG="\${FECLORA_MOCK_CONFIG:-fedora-45-x86_64}"
OUTPUT_DIR="\${FECLORA_WAYLAND_RPM_DIR:-$ROOT_DIR/out/wayland-rpms}"
WORK_PARENT="\${FECLORA_WAYLAND_WORK_PARENT:-$ROOT_DIR/out}"
PATCHER="$ROOT_DIR/build/patch-fedora-wayland-spec.py"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "\${EUID}" -eq 0 ]]; then
  fail "Run Mock as an unprivileged user in the mock group, not as root."
fi
[[ -s "$PATCHER" ]] || fail "Fedora spec patcher is missing."
for command in git fedpkg mock rpmbuild rpm python3; do
  command -v "$command" >/dev/null 2>&1 || fail "Required build command is missing: $command"
done

# This build must use Fedora 45's package branches and Mock root.
# shellcheck disable=SC1091
. /etc/os-release
[[ "\${ID:-}" == fedora && "\${VERSION_ID:-}" == 45 ]] ||
  fail "Build the custom RPMs on a Fedora 45 host; detected \${PRETTY_NAME:-unknown}."
id -nG | tr ' ' '\n' | grep -Fxq mock ||
  fail "The current user must be in the mock group (log out/in after adding it)."
[[ -f "/etc/mock/\${MOCK_CONFIG}.cfg" ]] ||
  fail "Mock configuration /etc/mock/\${MOCK_CONFIG}.cfg is missing."

[[ ! -e "$OUTPUT_DIR" ]] || fail "Output directory already exists; move it aside first: $OUTPUT_DIR"
mkdir -p "$WORK_PARENT"
WORK_DIR="$(mktemp -d "$WORK_PARENT/.feclora-wayland-rpms.XXXXXX")"
RESULTS="$WORK_DIR/results"
mkdir -p "$RESULTS"
trap 'rm -rf -- "$WORK_DIR"' EXIT

prepare_fedora_srpm() {
  local package="$1" source_dir="$WORK_DIR/$package" top="$WORK_DIR/rpmbuild-$package"
  local spec_file srpm
  git clone --depth 1 --branch f45 "https://src.fedoraproject.org/rpms/\${package}.git" "$source_dir"
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
  (("\${#srpms[@]}" == 1)) || fail "Expected exactly one Fedora 45 $package SRPM."
  srpm="\${srpms[0]}"
  printf '%s\n' "$srpm"
}

build_mock_package() {
  local package="$1" srpm="$2" result_dir="$RESULTS/$package"
  mkdir -p "$result_dir"
  mock -r "$MOCK_CONFIG" --rebuild --resultdir="$result_dir" "$srpm"
}

find_binary_rpm() {
  local result_dir="$1" package="$2"
  local -a matches=()
  while IFS= read -r candidate; do
    [[ "$(rpm -qp --qf '%{NAME}' "$candidate")" == "$package" ]] && matches+=("$candidate")
  done < <(find "$result_dir" -maxdepth 1 -type f -name '*.rpm' ! -name '*.src.rpm' ! -name '*debuginfo*' -print)
  (("\${#matches[@]}" == 1)) || fail "Expected one $package binary RPM in $result_dir; found \${#matches[@]}."
  printf '%s\n' "\${matches[0]}"
}

printf '[1/5] Fetching and patching Fedora 45 Weston source...\n'
weston_srpm="$(prepare_fedora_srpm weston)"
printf '[2/5] Building Weston 15.0.1 in Mock...\n'
build_mock_package weston "$weston_srpm"

printf '[3/5] Fetching and building GTK 4.24.1...\n'
gtk4_srpm="$(prepare_fedora_srpm gtk4)"
build_mock_package gtk4 "$gtk4_srpm"
gtk4_runtime="$(find_binary_rpm "$RESULTS/gtk4" gtk4)"
gtk4_devel="$(find_binary_rpm "$RESULTS/gtk4" gtk4-devel)"

printf '[4/5] Rebuilding libadwaita 1.10.0 against the custom GTK4 RPMs...\n'
libadwaita_srpm="$(prepare_fedora_srpm libadwaita)"
mock -r "$MOCK_CONFIG" --init
mock -r "$MOCK_CONFIG" --install "$gtk4_runtime" "$gtk4_devel"
mkdir -p "$RESULTS/libadwaita"
mock -r "$MOCK_CONFIG" --rebuild --no-clean \
  --resultdir="$RESULTS/libadwaita" "$libadwaita_srpm"

printf '[5/5] Auditing the actual binary RPM payloads and dependencies...\n'
weston_rpm="$(find_binary_rpm "$RESULTS/weston" weston)"
weston_libs_rpm="$(find_binary_rpm "$RESULTS/weston" weston-libs)"
libadwaita_rpm="$(find_binary_rpm "$RESULTS/libadwaita" libadwaita)"
bash "$ROOT_DIR/build/verify-wayland-rpms.sh" \
  "$weston_rpm" "$weston_libs_rpm" "$gtk4_runtime" "$libadwaita_rpm" "$gtk4_devel"

mkdir -p "$OUTPUT_DIR"
cp "$weston_rpm" "$weston_libs_rpm" "$gtk4_runtime" "$gtk4_devel" "$libadwaita_rpm" "$OUTPUT_DIR/"
cp "$WORK_DIR/source-commits.tsv" "$OUTPUT_DIR/"
rpm -qp --qf '%{NAME} %{VERSION}-%{RELEASE} source=%{SOURCERPM}\n' "$OUTPUT_DIR"/*.rpm
printf 'Strictly audited RPMs copied to %s\n' "$OUTPUT_DIR"
printf 'The Live Kickstart has not been changed to install or enable these RPMs.\n'
