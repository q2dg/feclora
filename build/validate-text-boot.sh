#!/usr/bin/env bash
# Literal grep patterns intentionally match Kickstart source text.
# shellcheck disable=SC2016
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
BUILD="$ROOT_DIR/build/build-iso.sh"
GTK="$ROOT_DIR/src/feclora/data/feclora-gtk.service"
READY="$ROOT_DIR/src/feclora/data/feclora-gtk-ready"
TERMINAL="$ROOT_DIR/src/feclora/data/feclora-root-terminal.service"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

for file in "$KS" "$BASE" "$BUILD" "$GTK" "$READY" "$TERMINAL"; do
  [[ -s "$file" ]] || fail "Required boot file is missing: $file"
done

grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service feclora-root-terminal.service' "$KS" || fail "GTK tty1 kiosk and tty2 maintenance shell must be enabled."
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS"; then
  fail "Textual must not be enabled as the production boot route."
fi
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk.service" "$TARGET_ROOT/etc/systemd/system/feclora-gtk.service"' "$KS" || fail "GTK systemd unit must be installed."
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk-ready" "$TARGET_ROOT/usr/libexec/feclora/feclora-gtk-ready"' "$KS" || fail "GTK first-frame readiness helper must be installed."
grep -Fxq 'ExecStart=/usr/bin/weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- /usr/bin/python3 -m feclora.gui_gtk' "$GTK" || fail "GTK service must launch Weston DRM/KMS with the GTK frontend."
grep -Fxq 'Environment=GDK_BACKEND=wayland' "$GTK" || fail "GTK must use native Wayland."
grep -Fxq 'UnsetEnvironment=DISPLAY XAUTHORITY' "$GTK" || fail "GTK service must not inherit X11 display state."
grep -Fxq 'TTYPath=/dev/tty1' "$GTK" || fail "GTK kiosk must own tty1."
grep -Fxq 'ExecStartPost=+/usr/libexec/feclora/feclora-gtk-ready' "$GTK" || fail "GTK kiosk must report its first rendered frame."
grep -Fxq 'TTYPath=/dev/tty2' "$TERMINAL" || fail "Maintenance shell must own tty2."
grep -Fq 'systemctl --root="$TARGET_ROOT" mask getty@tty1.service getty@tty2.service' "$KS" || fail "Getty must not compete for tty1 or tty2."
grep -Fq 'mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service' "$KS" || fail "kmscon must not own appliance VTs."
grep -Fq 'console=tty0 rd.systemd.show_status=1 systemd.show_status=1' "$BUILD" || fail "Boot must retain visible kernel and systemd messages."
grep -Fq 'systemctl --root="$TARGET_ROOT" set-default multi-user.target' "$KS" || fail "Appliance must retain the minimal multi-user target."
grep -Fxq -- '-xorg-x11-server-Xorg' "$KS" || fail "Kickstart must exclude Xorg."
grep -Fxq -- '-xorg-x11-server-Xwayland' "$KS" || fail "Kickstart must exclude XWayland."

for package in weston weston-libs gtk4 libadwaita python3-gobject; do
  grep -Fxq "$package" "$KS" || fail "Kickstart must install Fedora's official $package RPM."
  grep -Fxq "$package" "$BASE" || fail "Base manifest must include Fedora's official $package RPM."
done
if grep -Eiq '(^|[[:space:]])(cage|xorg-x11-server-Xorg|xorg-x11-server-Xwayland)([[:space:]]|$)' "$KS" "$BASE"; then
  fail "Do not install Cage, Xorg or XWayland server."
fi

if (( ERRORS > 0 )); then
  printf 'GTK production boot validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'GTK/Weston production boot checks passed; Textual remains temporarily installed for rollback.\n'
