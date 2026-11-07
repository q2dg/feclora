#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS_FILE="${FECLORA_KS:-${ROOT_DIR}/kickstart/feclora-live.ks}"
RESULT_DIR="${FECLORA_RESULT_DIR:-${ROOT_DIR}/out}"
INSTALL_ISO="${FEDORA_INSTALL_ISO:-}"
RELEASEVER="${FECLORA_RELEASEVER:-43}"

usage() {
  cat <<'EOF'
Usage:
  FEDORA_INSTALL_ISO=/path/to/Fedora-43-x86_64-DVD.iso ./build/build-iso.sh

Environment:
  FEDORA_INSTALL_ISO  Fedora 43 x86_64 DVD installation ISO (required).
  FECLORA_KS          Kickstart file (default: kickstart/feclora-live.ks).
  FECLORA_RESULT_DIR  Output directory (default: out/).
  FECLORA_RELEASEVER  Fedora release version (default: 43).

Run on a Fedora 43 x86_64 build host. Install lorax, lorax-lmc-virt,
qemu-kvm and the other build dependencies first. The build requires root.
The build uses QEMU virtualization; it deliberately does not use --no-virt.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "${INSTALL_ISO}" || ! -f "${INSTALL_ISO}" ]]; then
  echo "FEDORA_INSTALL_ISO must point to an existing Fedora DVD ISO." >&2
  usage >&2
  exit 2
fi

if [[ ! -f "${KS_FILE}" ]]; then
  echo "Kickstart file not found: ${KS_FILE}" >&2
  exit 2
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This initial build target is x86_64; host is $(uname -m)." >&2
  exit 2
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (for example: sudo -E $0)." >&2
  exit 2
fi

for cmd in livemedia-creator qemu-system-x86_64; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}. Install the build dependencies first." >&2
    exit 127
  fi
done

mkdir -p "${RESULT_DIR}"
RESULT_DIR="$(cd -- "${RESULT_DIR}" && pwd)"

printf 'Fedora release: %s\nInstaller ISO: %s\nKickstart: %s\nOutput: %s\n' \
  "${RELEASEVER}" "${INSTALL_ISO}" "${KS_FILE}" "${RESULT_DIR}"

livemedia-creator \
  --make-iso \
  --iso "${INSTALL_ISO}" \
  --ks "${KS_FILE}" \
  --resultdir "${RESULT_DIR}" \
  --project feclora \
  --releasever "${RELEASEVER}" \
  --ram 4096 \
  --vcpus 4 \
  --iso-only \
  --iso-name feclora-live.iso

printf 'Build command completed. Inspect the ISO and logs under: %s\n' "${RESULT_DIR}"
