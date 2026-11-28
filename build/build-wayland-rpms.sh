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
cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$status" -eq 0 ]]; then
    rm -rf -- "$WORK_DIR" || status=$?
  else
    printf 'RPM build failed; preserving workspace and Mock logs at %s\n' "$WORK_DIR" >&2
  fi
  exit "$status"
}
trap cleanup EXIT

prepare_fedora_srpm() {
  local package="$1" source_ref="$2"
  local source_dir="$WORK_DIR/$package" top="$WORK_DIR/rpmbuild-$package"
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
  local package="$1" srpm="$2"
  local result_dir="$RESULTS/$package"
  mkdir -p "$result_dir"
  mock -r "$MOCK_CONFIG" --rebuild --resultdir="$result_dir" "$srpm"
}

build_mock_package_preserving_root() {
  local package="$1" srpm="$2"
  local result_dir="$RESULTS/$package"
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

printf '[6/6] Auditing every generated non-source binary RPM payload, dependency and capability...\n'
weston_rpm="$(find_binary_rpm "$RESULTS/weston" weston)"
weston_libs_rpm="$(find_binary_rpm "$RESULTS/weston" weston-libs)"
runtime_rpms=("$weston_rpm" "$weston_libs_rpm" "$gtk4_runtime" "$libadwaita_rpm" "$cairo_runtime" "$cairo_gobject")
mapfile -t audit_rpms < <(
  find "$RESULTS" -mindepth 2 -maxdepth 2 -type f -name '*.rpm' ! -name '*.src.rpm' -print | sort
)
(("${#audit_rpms[@]}" >= 6)) || fail "No complete set of generated binary RPMs was found."
bash "$ROOT_DIR/build/verify-wayland-rpms.sh" "${audit_rpms[@]}"

printf '[runtime audit] Resolving the complete Fedora 45 candidate dependency closure...\n'
RUNTIME_MOCK_CONFIG="$WORK_DIR/fedora-45-runtime.cfg"
RUNTIME_AUDIT_EXT="feclora-runtime-audit-${BASHPID}"
cp "/etc/mock/${MOCK_CONFIG}.cfg" "$RUNTIME_MOCK_CONFIG"
cat >> "$RUNTIME_MOCK_CONFIG" <<'EOF'
# The closure root must not inherit the RPM build toolchain. Resolve only the
# candidate runtime transaction plus Fedora 45 dependencies.
config_opts['chroot_setup_cmd'] = 'install bash coreutils rpm dnf5'
EOF
mock -r "$RUNTIME_MOCK_CONFIG" --uniqueext "$RUNTIME_AUDIT_EXT" --init
mock -r "$RUNTIME_MOCK_CONFIG" --uniqueext "$RUNTIME_AUDIT_EXT" --install \
  "${runtime_rpms[@]}" python3-gobject python3-cairo \
  2>&1 | tee "$WORK_DIR/runtime-install.log"
runtime_root="$(mock -r "$RUNTIME_MOCK_CONFIG" --uniqueext "$RUNTIME_AUDIT_EXT" --print-root-path)"
[[ -d "$runtime_root" ]] || fail "Mock did not create the isolated runtime audit root: $runtime_root"
bash "$ROOT_DIR/build/verify-wayland-rpms.sh" --installed-root "$runtime_root" "${audit_rpms[@]}" \
  2>&1 | tee "$WORK_DIR/runtime-audit.log"
rpm --root "$runtime_root" -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > "$WORK_DIR/runtime-closure.txt"
mock -r "$RUNTIME_MOCK_CONFIG" --uniqueext "$RUNTIME_AUDIT_EXT" --scrub=chroot

mkdir -p "$OUTPUT_DIR/build-deps" "$OUTPUT_DIR/build-logs" "$OUTPUT_DIR/sources"
cp "${runtime_rpms[@]}" "$OUTPUT_DIR/"
for package in cairo weston gtk4 libadwaita; do
  package_result_dir="$RESULTS/$package"
  package_log_dir="$OUTPUT_DIR/build-logs/$package"
  mkdir -p "$package_log_dir"
  mapfile -t package_logs < <(find "$package_result_dir" -maxdepth 1 -type f -name '*.log' -print | sort)
  (("${#package_logs[@]}" > 0)) || fail "Mock did not preserve build logs for $package."
  cp "${package_logs[@]}" "$package_log_dir/"
done
cp "$cairo_srpm" "$weston_srpm" "$gtk4_srpm" "$libadwaita_srpm" "$OUTPUT_DIR/sources/"
declare -A runtime_rpm_paths=()
for rpm_file in "${runtime_rpms[@]}"; do
  runtime_rpm_paths["$rpm_file"]=1
done
for rpm_file in "${audit_rpms[@]}"; do
  [[ -n "${runtime_rpm_paths[$rpm_file]+x}" ]] && continue
  package_name="$(rpm -qp --qf '%{NAME}' "$rpm_file")"
  case "$package_name" in
    *-debuginfo|*-debugsource) continue ;;
  esac
  cp "$rpm_file" "$OUTPUT_DIR/build-deps/"
done
cp "$WORK_DIR/source-commits.tsv" "$OUTPUT_DIR/"
cp "$WORK_DIR/runtime-closure.txt" "$OUTPUT_DIR/"
mkdir -p "$OUTPUT_DIR/build-logs/runtime-closure"
cp "$WORK_DIR/runtime-install.log" "$WORK_DIR/runtime-audit.log" "$OUTPUT_DIR/build-logs/runtime-closure/"
{
  printf 'Fedora host: %s\n' "${PRETTY_NAME:-unknown}"
  printf 'Mock config: %s\n' "$MOCK_CONFIG"
  printf 'Build timestamp (UTC): %s\n' "$(date -u +%FT%TZ)"
  mock --version
  rpm --version
  rpmbuild --version
} > "$OUTPUT_DIR/build-environment.txt"
rpm -qp --qf '%{NAME} %{EPOCH}:%{VERSION}-%{RELEASE} source=%{SOURCERPM}\n' \
  "$OUTPUT_DIR"/*.rpm "$OUTPUT_DIR"/build-deps/*.rpm
printf 'Strictly audited runtime RPMs copied to %s\n' "$OUTPUT_DIR"
printf 'Non-runtime, non-debug RPM subpackages copied to %s/build-deps (do not add these to the Live image).\n' "$OUTPUT_DIR"
printf 'All generated binary RPMs, including debug subpackages, were audited; debug packages were not copied.\n'
printf 'The Live Kickstart has not been changed to install or enable these RPMs.\n'
