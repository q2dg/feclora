#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_FILE="${ROOT_DIR}/packages/build-host.txt"

[[ -s "${PACKAGE_FILE}" ]] || {
  echo "Build-host package manifest is missing or empty: ${PACKAGE_FILE}" >&2
  exit 1
}

mapfile -t packages < <(awk 'NF && $1 !~ /^#/ { print $1 }' "${PACKAGE_FILE}")
(("${#packages[@]}")) || {
  echo "Build-host package manifest contains no packages." >&2
  exit 1
}
for package in "${packages[@]}"; do
  [[ "${package}" =~ ^[A-Za-z0-9][A-Za-z0-9+_.-]*$ ]] || {
    echo "Invalid package name in build-host manifest: ${package}" >&2
    exit 1
  }
done

if [[ "${EUID}" -eq 0 ]]; then
  dnf install -y "${packages[@]}"
elif command -v sudo >/dev/null 2>&1; then
  sudo dnf install -y "${packages[@]}"
else
  echo "Run as root or install sudo to install build dependencies." >&2
  exit 1
fi
