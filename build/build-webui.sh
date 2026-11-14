#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/webui"
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the Cockpit frontend. Install nodejs and npm." >&2
  exit 127
fi
cd "${WEB_DIR}"
if [[ -f package-lock.json ]]; then
  npm ci --no-audit --no-fund
else
  echo "WARNING: webui/package-lock.json is missing; transitive npm dependencies are not reproducibly pinned." >&2
  npm install --no-audit --no-fund
fi
npm run build
test -s dist/index.html
test -s dist/manifest.json
