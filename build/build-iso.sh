#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS_FILE="${FECLORA_KS:-${ROOT_DIR}/kickstart/feclora-live.ks}"
RESULT_DIR="${FECLORA_RESULT_DIR:-${ROOT_DIR}/out}"
INSTALL_ISO="${FEDORA_INSTALL_ISO:-}"
RELEASEVER="${FECLORA_RELEASEVER:-45}"
BUILD_RAM="${FECLORA_BUILD_RAM:-}"
BUILD_VCPUS="${FECLORA_BUILD_VCPUS:-}"
BUILD_PROXY="${FECLORA_BUILD_PROXY:-}"

usage() {
  cat <<'EOF'
Usage:
  FEDORA_INSTALL_ISO=/path/to/Fedora-45-x86_64-DVD.iso ./build/build-iso.sh

Environment:
  FEDORA_INSTALL_ISO  Fedora 45 x86_64 DVD installation ISO (required).
  FECLORA_KS          Kickstart file (default: kickstart/feclora-live.ks).
  FECLORA_RESULT_DIR  Output directory (default: out/).
  FECLORA_RELEASEVER  Fedora release version (default: 45).
  FECLORA_BUILD_RAM   QEMU installer RAM in MiB (default: 50% of host RAM, min 4096, max 16384).
  FECLORA_BUILD_VCPUS QEMU virtual CPUs (default: host CPUs, min 1, max 8).
  FECLORA_BUILD_PROXY Optional HTTP proxy for Fedora package downloads (also cacheable).

Run on a Fedora 45 x86_64 build host. Install lorax, lorax-lmc-virt,
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
[[ -f "${KS_FILE}" ]] || { echo "Kickstart file not found: ${KS_FILE}" >&2; exit 2; }
[[ "$(uname -m)" == "x86_64" ]] || { echo "This initial build target is x86_64; host is $(uname -m)." >&2; exit 2; }
[[ "${EUID}" -eq 0 ]] || { echo "Run as root (for example: sudo -E $0)." >&2; exit 2; }

for cmd in livemedia-creator mkksiso qemu-system-x86_64 sha256sum xorriso lsinitrd; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "Required command not found: ${cmd}. Install the build dependencies first." >&2; exit 127; }
done

RESULT_DIR="$(realpath -m -- "${RESULT_DIR}")"
if [[ -e "${RESULT_DIR}" ]]; then
  echo "Output directory already exists: ${RESULT_DIR}" >&2
  echo "Move it aside or run 'make clean' before building again." >&2
  exit 1
fi

SECONDS=0
echo "[1/4] Checking build host..."
bash "${ROOT_DIR}/build/preflight.sh"

echo "[2/4] Building Cockpit frontend..."
bash "${ROOT_DIR}/build/build-webui.sh"
echo "Frontend phase: ${SECONDS}s"

# Scale QEMU resources to the build host, while retaining conservative bounds.
HOST_CPUS="$(nproc)"
if [[ -z "${BUILD_VCPUS}" ]]; then
  BUILD_VCPUS="${HOST_CPUS}"
  (( BUILD_VCPUS > 8 )) && BUILD_VCPUS=8
  (( BUILD_VCPUS < 1 )) && BUILD_VCPUS=1
fi
if [[ -z "${BUILD_RAM}" ]]; then
  HOST_RAM_MIB="$(awk '/MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)"
  BUILD_RAM=$((HOST_RAM_MIB / 2))
  (( BUILD_RAM > 16384 )) && BUILD_RAM=16384
  (( BUILD_RAM < 4096 )) && BUILD_RAM=4096
fi
[[ "${BUILD_VCPUS}" =~ ^[1-9][0-9]*$ ]] || { echo "FECLORA_BUILD_VCPUS must be a positive integer." >&2; exit 2; }
[[ "${BUILD_RAM}" =~ ^[1-9][0-9]*$ ]] || { echo "FECLORA_BUILD_RAM must be a positive integer (MiB)." >&2; exit 2; }

mkdir -p "$(dirname -- "${RESULT_DIR}")"
WORK_DIR="$(mktemp -d "$(dirname -- "${RESULT_DIR}")/.feclora-build.XXXXXX")"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

echo "[3/4] Preparing augmented installer ISO..."
APP_STAGE="${WORK_DIR}/feclora-app"
AUGMENTED_ISO="${WORK_DIR}/feclora-installer.iso"
mkdir -p "${APP_STAGE}/src" "${APP_STAGE}/webui/dist"

# Lorax builds the ISO boot menus from its own templates, independently of
# /etc/default/grub in the installed Live filesystem. Override both firmware
# variants so the first entry boots immediately without showing the menu.
LORAX_TEMPLATE_SOURCE="${FECLORA_LORAX_TEMPLATES:-/usr/share/lorax/templates.d/99-generic}"
LORAX_TEMPLATE_DIR="${WORK_DIR}/lorax-templates"
[[ -d "${LORAX_TEMPLATE_SOURCE}/live/config_files/x86" ]] || {
  echo "Lorax live templates not found under ${LORAX_TEMPLATE_SOURCE}." >&2
  exit 1
}
cp -a "${LORAX_TEMPLATE_SOURCE}" "${LORAX_TEMPLATE_DIR}"
for grub_cfg in \
  "${LORAX_TEMPLATE_DIR}/live/config_files/x86/grub2-bios.cfg" \
  "${LORAX_TEMPLATE_DIR}/live/config_files/x86/grub2-efi.cfg"; do
  [[ -f "${grub_cfg}" ]] || { echo "Required Lorax GRUB template missing: ${grub_cfg}" >&2; exit 1; }
  sed -i -E 's/^set default=.*/set default="0"/; s/^set timeout=.*/set timeout=0/' "${grub_cfg}"
  if ! grep -q '^set timeout_style=' "${grub_cfg}"; then
    sed -i '/^set timeout=0$/a set timeout_style=hidden' "${grub_cfg}"
  else
    sed -i 's/^set timeout_style=.*/set timeout_style=hidden/' "${grub_cfg}"
  fi
done
cp -a "${ROOT_DIR}/src/feclora" "${APP_STAGE}/src/feclora"
cp -a "${ROOT_DIR}/webui/dist/." "${APP_STAGE}/webui/dist/"

mkksiso --add "${APP_STAGE}" "${KS_FILE}" "${INSTALL_ISO}" "${AUGMENTED_ISO}"

echo "[4/4] Creating Live ISO with ${BUILD_VCPUS} vCPUs and ${BUILD_RAM} MiB RAM..."
LMC_ARGS=(
  --make-iso
  --iso "${AUGMENTED_ISO}"
  --ks "${KS_FILE}"
  --resultdir "${RESULT_DIR}"
  --project feclora
  --releasever "${RELEASEVER}"
  --ram "${BUILD_RAM}"
  --vcpus "${BUILD_VCPUS}"
  --iso-only
  --iso-name feclora-live.iso
  --lorax-templates "${LORAX_TEMPLATE_DIR}"
  --extra-boot-args "rhgb quiet vt.global_cursor_default=0"
)
if [[ -n "${BUILD_PROXY}" ]]; then
  LMC_ARGS+=(--proxy "${BUILD_PROXY}")
fi
livemedia-creator "${LMC_ARGS[@]}"

ISO_FILE="${RESULT_DIR}/feclora-live.iso"
REPORT="${RESULT_DIR}/boot-initrd-plymouth-check.txt"
[[ -s "$ISO_FILE" ]] || { echo "ISO build did not create $ISO_FILE." >&2; exit 1; }
bash "${ROOT_DIR}/build/verify-iso-boot-visuals.sh" "$ISO_FILE" "$REPORT"

printf 'Build command completed in %ss. Inspect the ISO and logs under: %s\n' "${SECONDS}" "${RESULT_DIR}"
