#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for file in \
  build/build-iso.sh build/preflight.sh build/install-host-deps.sh \
  build/check_docs.py build/validate-gtk-boot.sh build/verify-iso-text-boot.sh \
  build/verify-wayland-rpms.sh kickstart/feclora-live.ks packages/base.txt \
  packages/build-host.txt requirements-gui.txt \
  src/feclora/gui_gtk.py src/feclora/gtk_api.py src/feclora/ui_api.py \
  src/feclora/api.py src/feclora/data/feclora-api \
  src/feclora/data/feclora-gtk.service src/feclora/data/feclora-gtk-ready \
  src/feclora/data/feclora-root-terminal.service \
  src/feclora/data/feclora-local-operation-recovery.service \
  tests/test_gtk_api.py tests/test_gtk_frontend.py tests/test_kiosk_boot.py \
  tests/test_ui_api.py tests/test_ui_catalog.py tests/test_wayland_rpm_guard.py; do
  [[ -s "$file" ]] || fail "Required file is missing or empty: $file"
done

if grep -Eq '(^|[[:space:]])python3-textual([[:space:]]|$)' packages/base.txt kickstart/feclora-live.ks; then
  fail "The obsolete Textual runtime package must not be installed."
fi
if find src/feclora -maxdepth 2 -type f \( -name 'tui.py' -o -name 'tui_api.py' \) | grep -q .; then
  fail "Obsolete TUI modules remain in the source tree."
fi

grep -Fq 'Environment=GDK_BACKEND=wayland' src/feclora/data/feclora-gtk.service \
  || fail "GTK must use native Wayland."
grep -Fq 'Environment=LIBSEAT_BACKEND=logind' src/feclora/data/feclora-gtk.service \
  || fail "Weston must use logind seat management."
grep -Fq 'UnsetEnvironment=DISPLAY XAUTHORITY' src/feclora/data/feclora-gtk.service \
  || fail "The GTK service must not inherit X11 display state."
grep -Fq 'ExecStart=/usr/bin/weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- /usr/bin/python3 -m feclora.gui_gtk' src/feclora/data/feclora-gtk.service \
  || fail "The production service must launch the GTK kiosk through Weston DRM/KMS."

bash build/validate-gtk-boot.sh
python3 build/check_docs.py
python3 -m compileall -q src tests build
python3 -m unittest discover -s tests -p 'test_*.py' -v

printf 'Static validation and hardware-independent tests completed. This does not prove that the ISO builds or boots.\n'
