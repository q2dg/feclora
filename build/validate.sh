#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for file in \
  build/build-iso.sh build/preflight.sh build/install-host-deps.sh \
  build/check_docs.py build/validate-text-boot.sh build/validate-gtk-candidate.sh \
  build/build-wayland-rpms.sh build/patch-fedora-wayland-spec.py \\
  build/verify-iso-text-boot.sh build/verify-wayland-rpms.sh \
  kickstart/feclora-live.ks packages/base.txt packages/build-host.txt \
  requirements-test.txt requirements-gui.txt \
  src/feclora/tui.py src/feclora/tui_api.py src/feclora/gui_gtk.py \
  src/feclora/gtk_api.py src/feclora/ui_api.py src/feclora/api.py \
  src/feclora/data/feclora-api src/feclora/data/feclora-tui.service \
  src/feclora/data/feclora-tui-ready src/feclora/data/feclora-gtk.service \
  src/feclora/data/feclora-gtk-ready src/feclora/data/feclora-root-terminal.service \
  src/feclora/data/feclora-local-operation-recovery.service \
  tests/test_tui.py tests/test_tui_api.py tests/test_gtk_api.py \
  tests/test_gtk_frontend.py tests/test_kiosk_boot.py tests/test_ui_api.py \
  tests/test_ui_catalog.py tests/test_wayland_rpm_guard.py \
  tests/test_wayland_spec_patch.py; do
  [[ -s "$file" ]] || fail "Required file is missing or empty: $file"
done

if grep -Eq '(^|[[:space:]])(weston|weston-libs|gtk4|libadwaita)([[:space:]]|$)' \
  packages/base.txt kickstart/feclora-live.ks; then
  fail "Stock Fedora graphical RPMs must not enter the Live image before strict X11-free rebuilds pass."
fi
grep -Fxq 'python3-textual' packages/base.txt || fail "Textual must remain installed until GTK acceptance is complete."
grep -Fxq 'python3-textual' kickstart/feclora-live.ks || fail "Kickstart must retain Textual as the production UI."

bash -n build/*.sh
bash build/validate-text-boot.sh
bash build/validate-gtk-candidate.sh
python3 build/check_docs.py
python3 -m compileall -q src tests build
python3 -m unittest discover -s tests -p 'test_*.py' -v

printf 'Static validation and hardware-independent tests completed. This does not prove that the ISO builds or boots.\n'
