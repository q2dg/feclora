#!/usr/bin/env bash
# Compatibility entry point: GTK is a staged candidate, not the production boot UI.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/build/validate-gtk-candidate.sh" "$@"
