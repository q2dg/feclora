#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ISO="${FEDORA_INSTALL_ISO:-}"
KS_FILE="${FECLORA_KS:-${ROOT_DIR}/kickstart/feclora-live.ks}"
RESULT_DIR="${FECLORA_RESULT_DIR:-${ROOT_DIR}/out}"
RELEASEVER="${FECLORA_RELEASEVER:-45}"
MIN_FREE_GIB="${FECLORA_MIN_FREE_GIB:-20}"

fail() {
  printf 'PREFLIGHT ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso make preflight

Environment:
  FEDORA_INSTALL_ISO   Fedora DVD installer ISO (required).
  FECLORA_KS           Kickstart file (default: kickstart/feclora-live.ks).
  FECLORA_RESULT_DIR   Output directory (default: out/).
  FECLORA_RELEASEVER   Fedora release version (default: 45).
  FECLORA_MIN_FREE_GIB Minimum free space in output filesystem (default: 20 GiB).

This checks host prerequisites only. It does not build or boot an ISO.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

[[ -n "$INSTALL_ISO" && -f "$INSTALL_ISO" ]] ||
  fail "FEDORA_INSTALL_ISO must point to an existing installer ISO."
[[ -f "$KS_FILE" ]] || fail "Kickstart file not found: $KS_FILE"
[[ -d "$ROOT_DIR/src/feclora" ]] || fail "Application source directory is missing."
[[ "$(uname -m)" == "x86_64" ]] ||
  fail "Expected an x86_64 build host; detected $(uname -m)."
grep -qx 'ID=fedora' /etc/os-release ||
  fail "The build host must be Fedora 45; detected a non-Fedora distribution."
grep -qx 'VERSION_ID="45"' /etc/os-release ||
  fail "The build host must be Fedora 45; check /etc/os-release."
[[ "$RELEASEVER" == "45" ]] ||
  fail "The current Kickstart baseline is Fedora 45; FECLORA_RELEASEVER=$RELEASEVER is inconsistent."

if [[ "$EUID" -ne 0 ]]; then
  fail "Run preflight as root, for example: sudo -E make preflight FEDORA_INSTALL_ISO=..."
fi

for cmd in livemedia-creator mkksiso qemu-system-x86_64; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Required command not found: $cmd (install make deps)."
done

[[ -c /dev/kvm ]] || fail "/dev/kvm is unavailable; enable hardware virtualization and install/configure KVM."
[[ -r /dev/kvm && -w /dev/kvm ]] ||
  fail "The current user cannot read/write /dev/kvm."

mkdir -p "$RESULT_DIR"
RESULT_DIR="$(cd -- "$RESULT_DIR" && pwd)"
available_kib="$(df -Pk "$RESULT_DIR" | awk 'NR == 2 {print $4}')"
[[ "$available_kib" =~ ^[0-9]+$ ]] || fail "Could not determine free space for $RESULT_DIR."
[[ "$MIN_FREE_GIB" =~ ^[1-9][0-9]*$ ]] || fail "FECLORA_MIN_FREE_GIB must be a positive integer."
required_kib=$((MIN_FREE_GIB * 1024 * 1024))
(( available_kib >= required_kib )) ||
  fail "Only $((available_kib / 1024 / 1024)) GiB free in $RESULT_DIR; need at least $MIN_FREE_GIB GiB (configurable via FECLORA_MIN_FREE_GIB)."

printf 'Preflight passed.\n'
host_name="$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | tr -d '"')"
printf '  Host: %s (%s)\n' "${host_name:-unknown}" "$(uname -m)"
printf '  Fedora target: %s\n' "$RELEASEVER"
printf '  Installer ISO: %s\n' "$INSTALL_ISO"
printf '  Kickstart: %s\n' "$KS_FILE"
printf '  Output directory: %s\n' "$RESULT_DIR"
printf '  Free space: %s GiB (minimum: %s GiB)\n' "$((available_kib / 1024 / 1024))" "$MIN_FREE_GIB"
printf '  KVM: available\n'
printf 'This confirms host prerequisites only; ISO build and BIOS/UEFI boot remain unverified.\n'
