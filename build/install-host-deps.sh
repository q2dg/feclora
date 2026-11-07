#!/usr/bin/env bash
set -Eeuo pipefail

packages=(
  lorax
  lorax-lmc-virt
  qemu-kvm
  edk2-ovmf
)

if [[ "${EUID}" -eq 0 ]]; then
  dnf install -y "${packages[@]}"
elif command -v sudo >/dev/null 2>&1; then
  sudo dnf install -y "${packages[@]}"
else
  echo "Run as root or install sudo to install build dependencies." >&2
  exit 1
fi
