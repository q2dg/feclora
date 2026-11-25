#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
BUILD="$ROOT_DIR/build/build-iso.sh"
TUI="$ROOT_DIR/src/feclora/data/feclora-tui.service"
READY="$ROOT_DIR/src/feclora/data/feclora-tui-ready"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

for file in "$KS" "$BASE" "$BUILD" "$TUI" "$READY"; do
  [[ -s "$file" ]] || fail "Required boot file is missing: $file"
done

grep -Fxq 'python3-textual' "$KS" || fail "Kickstart must retain the current production Textual UI."
grep -Fxq 'python3-textual' "$BASE" || fail "Base manifest must retain the current production Textual UI."
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service"' "$KS" \
  || fail "Kickstart must install the current tty1 UI service."
grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS" \
  || fail "Textual must remain the production boot UI until GTK/Weston acceptance."
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service' "$KS"; then
  fail "GTK must not become the production boot route before functional parity and acceptance."
fi

grep -Fxq 'ExecStart=/usr/bin/python3 -m feclora.tui' "$TUI" \
  || fail "The current tty1 service must start Textual."
grep -Fxq 'TTYPath=/dev/tty1' "$TUI" || fail "The current UI must own tty1."
grep -Fxq 'ExecStartPost=+/usr/libexec/feclora/feclora-tui-ready' "$TUI" \
  || fail "The current UI must report its first rendered screen."
grep -Fq 'FECLORA_BOOT_SMOKE rendered' "$READY" \
  || fail "The readiness helper must report the first rendered screen."
grep -Fq 'console=tty0 rd.systemd.show_status=1 systemd.show_status=1' "$BUILD" \
  || fail "Boot must retain visible kernel and systemd messages."
grep -Fq 'systemctl --root="$TARGET_ROOT" mask getty@tty1.service' "$KS" \
  || fail "The login prompt must not compete for tty1."
grep -Fq 'systemctl --root="$TARGET_ROOT" set-default multi-user.target' "$KS" \
  || fail "The appliance must retain its minimal multi-user target."

if grep -Eiq '(^|[[:space:]])(cage|weston|weston-libs|gtk4|libadwaita|python3-gobject|xorg-x11-server-Xorg|xorg-x11-server-Xwayland)([[:space:]]|$)' "$KS" "$BASE"; then
  fail "Do not ship Cage or stock GTK/Weston packages before the X11-disabled Fedora rebuilds are ready."
fi

if (( ERRORS > 0 )); then
  printf 'Textual production boot validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'Textual production boot checks passed; GTK/Weston remains gated on parity.\n'
