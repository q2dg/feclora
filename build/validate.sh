#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
errors=0
fail() { printf 'ERROR: %s\n' "$*" >&2; errors=$((errors + 1)); }

for file in "$ROOT_DIR/build/build-iso.sh" "$ROOT_DIR/build/install-host-deps.sh" "$ROOT_DIR/kickstart/feclora-live.ks" "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/src/feclora/storage/inventory.py" "$ROOT_DIR/src/feclora/ui/dialog_app.py" "$ROOT_DIR/scripts/feclora-ui.sh"; do
  [[ -f "$file" ]] || fail "Required project file is missing: $file"
done

if [[ -f "$ROOT_DIR/kickstart/feclora-live.ks" ]]; then
  grep -q '^#version=F43$' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not declare Fedora 43 (#version=F43)."
  grep -q '^part / ' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not define a root partition."
  grep -qx 'dialog' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include dialog."
fi

if [[ -f "$ROOT_DIR/build/build-iso.sh" ]]; then
  grep -q -- '--make-iso' "$ROOT_DIR/build/build-iso.sh" || fail "Build script does not request ISO output."
  if grep -Eq '^[[:space:]]+--no-virt([[:space:]]|$)' "$ROOT_DIR/build/build-iso.sh"; then
    fail "Unsafe --no-virt mode must not be enabled by the default build."
  fi
fi

if ! grep -qx 'dialog' "$ROOT_DIR/packages/base.txt"; then
  fail "Runtime package list does not include dialog."
fi

while IFS= read -r -d '' script; do
  bash -n "$script" || fail "Bash syntax check failed: $script"
done < <(find "$ROOT_DIR/build" "$ROOT_DIR/scripts" -type f -name '*.sh' -print0 2>/dev/null || true)

if (( errors > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$errors" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'
