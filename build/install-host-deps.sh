#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  dnf install -y lorax lorax-lmc-virt qemu-kvm
elif command -v sudo >/dev/null 2>&1; then
  sudo dnf install -y lorax lorax-lmc-virt qemu-kvm
else
  echo "Run as root or install sudo to install build dependencies." >&2
  exit 1
fi
