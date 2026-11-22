#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# make build invokes the ISO builder through sudo. Drop back to the
# original caller for npm so node_modules, the npm cache and dist remain
# writable by the developer instead of becoming root-owned.
if [[ "${EUID}" -eq 0 && "${SUDO_UID:-}" =~ ^[1-9][0-9]* ]]; then
  command -v runuser >/dev/null 2>&1 || {
    echo "runuser is required to build the frontend as the invoking user." >&2
    exit 127
  }
  USER_HOME="$(getent passwd "${SUDO_UID}" | cut -d: -f6)"
  [[ -n "${USER_HOME}" ]] || {
    echo "Could not determine the invoking user's home directory." >&2
    exit 1
  }
  exec runuser -u "${SUDO_UID}" -- env HOME="${USER_HOME}" bash "${BASH_SOURCE[0]}" "$@"
fi
WEB_DIR="${ROOT_DIR}/webui"
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the Cockpit frontend. Install nodejs and npm." >&2
  exit 127
fi
cd "${WEB_DIR}"
if [[ ! -f package-lock.json ]]; then
  echo "ERROR: webui/package-lock.json is required for reproducible frontend builds." >&2
  exit 1
fi

# npm ci is deterministic but removes node_modules on every invocation.
# Reuse the exact lockfile-matched dependency tree between ISO builds.
LOCK_FINGERPRINT="$(sha256sum package.json package-lock.json | sha256sum | awk '{print $1}')"
INSTALLED_FINGERPRINT=""
if [[ -s node_modules/.feclora-lock-fingerprint ]]; then
  INSTALLED_FINGERPRINT="$(<node_modules/.feclora-lock-fingerprint)"
fi
if [[ ! -d node_modules ]] || [[ "${LOCK_FINGERPRINT}" != "${INSTALLED_FINGERPRINT}" ]]; then
  echo "Installing frontend dependencies (lockfile changed or cache missing)..."
  npm ci --no-audit --no-fund
  printf '%s\n' "${LOCK_FINGERPRINT}" > node_modules/.feclora-lock-fingerprint
else
  echo "Reusing frontend dependencies matching package-lock.json."
fi

npm run test:dependency-pins
npm run test:i18n
npm run test:api-contract
npm run build
test -s dist/index.html
test -s dist/manifest.json
