#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS_FILE="${FECLORA_KS:-${ROOT_DIR}/kickstart/feclora-live.ks}"
RESULT_DIR="${FECLORA_RESULT_DIR:-${ROOT_DIR}/out}"
INSTALL_ISO="${FEDORA_INSTALL_ISO:-}"

usage() {
  cat <<'EOF'
Usage:
  FEDORA_INSTALL_ISO=/path/to/Fedora-43-x86_64-DVD.iso ./build/build-iso.sh

Environment:
  FEDORA_INSTALL_ISO  Full Fedora 43 x86_64 DVD installation ISO (required).
  FECLORA_KS          Kickstart file (default: kickstart/feclora-live.ks).
  FECLORA_RESULT_DIR  Output directory (default: out/).

Run on a Fedora 43 x86_64 build host with lorax and lorax-lmc-novirt
installed. The build requires root privileges.
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

if ! command -v livemedia-creator >/dev/null 2>&1; then
  echo "livemedia-creator not found. Run build/install-host-deps.sh first." >&2
  exit 127
fi

mkdir -p "${RESULT_DIR}"
RESULT_DIR="$(cd -- "${RESULT_DIR}" && pwd)"

echo "Build input: ${INSTALL_ISO}"
echo "Kickstart:   ${KS_FILE}"
echo "Output:      ${RESULT_DIR}"

livemedia-creator \
  --make-iso \
  --no-virt \
  --iso "${INSTALL_ISO}" \
  --ks "${KS_FILE}" \
  --resultdir "${RESULT_DIR}"

echo "Build command completed. Inspect artifacts in: ${RESULT_DIR}"
