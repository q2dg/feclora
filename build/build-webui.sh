#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
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
