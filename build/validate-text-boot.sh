#!/usr/bin/env bash
# Literal grep patterns intentionally match shell source text, not expanded variables.
# shellcheck disable=SC2016
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
BUILD="$ROOT_DIR/build/build-iso.sh"
TUI="$ROOT_DIR/src/feclora/data/feclora-tui.service"
READY="$ROOT_DIR/src/feclora/data/feclora-tui-ready"
ROOT_TERMINAL="$ROOT_DIR/src/feclora/data/feclora-root-terminal.service"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

for file in "$KS" "$BASE" "$BUILD" "$TUI" "$READY" "$ROOT_TERMINAL"; do
  [[ -s "$file" ]] || fail "Required boot file is missing: $file"
done

grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service' "$KS" || fail "Kickstart must enable the GTK production UI."
grep -Fxq 'gtk4' "$BASE" || fail "Base manifest must include GTK4."
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service"' "$KS" \
  || fail "Kickstart must install the current tty1 UI service."
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui-ready"' "$KS" \
  || fail "Kickstart must install the Textual first-render readiness helper."
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk.service" "$TARGET_ROOT/etc/systemd/system/feclora-gtk.service"' "$KS" \
  || fail "The candidate GTK kiosk unit must be staged in the image."
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk-ready" "$TARGET_ROOT/usr/libexec/feclora/feclora-gtk-ready"' "$KS" \
  || fail "The candidate GTK first-render helper must be staged in the image."
grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS" \
  || fail "Textual must remain the production boot UI until GTK/Weston acceptance."
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS"; then
  fail "Textual must not be enabled as the production boot route."
fi

grep -Fxq 'ExecStart=/usr/bin/python3 -m feclora.tui' "$TUI" \
  || fail "The current tty1 service must start Textual."
grep -Fxq 'TTYPath=/dev/tty1' "$TUI" || fail "The current UI must own tty1."
grep -Fxq 'Conflicts=getty@tty1.service kmsconvt@tty1.service' "$TUI" || fail "The current UI must exclude Fedora 45 kmscon from tty1."
grep -Fxq 'Conflicts=getty@tty2.service kmsconvt@tty2.service' "$ROOT_TERMINAL" || fail "The maintenance shell must exclude Fedora 45 kmscon from tty2."
grep -Fq 'mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service' "$KS" || fail "All appliance VTs 1-6 must be reserved from Fedora 45 kmscon DRM ownership."
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
grep -Fxq -- '-xorg-x11-server-Xorg' "$KS" || fail "Kickstart must explicitly exclude the Xorg server."
grep -Fxq -- '-xorg-x11-server-Xwayland' "$KS" || fail "Kickstart must explicitly exclude the XWayland server."

for package in weston weston-libs gtk4 libadwaita python3-gobject; do
  grep -Fxq "$package" "$KS" || fail "Kickstart must install Fedora's official $package RPM."
  grep -Fxq "$package" "$BASE" || fail "Base manifest must include Fedora's official $package RPM."
done
if grep -Eiq '(^|[[:space:]])(cage|xorg-x11-server-Xorg|xorg-x11-server-Xwayland)([[:space:]]|$)' "$KS" "$BASE"; then
  fail "Do not install Cage, Xorg or the XWayland server in the native Wayland appliance."
fi

if (( ERRORS > 0 )); then
  printf 'GTK production boot validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'Textual production boot checks passed; official GTK/Weston RPMs are staged, but GTK remains gated on parity.\n'
