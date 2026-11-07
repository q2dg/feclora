#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m feclora.ui.dialog_app "$@"
