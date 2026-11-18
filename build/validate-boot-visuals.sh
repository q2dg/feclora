#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BUILD="$ROOT_DIR/build/build-iso.sh"
SERVICE="$ROOT_DIR/src/feclora/data/feclora-kiosk.service"
LAUNCH="$ROOT_DIR/src/feclora/data/feclora-kiosk-launch"
PAM="$ROOT_DIR/src/feclora/data/feclora-kiosk.pam"
THEME="$ROOT_DIR/src/feclora/data/plymouth"
fail() { echo "BOOT VISUAL VALIDATION ERROR: $*" >&2; exit 1; }

for package in plymouth plymouth-plugin-script librsvg2-tools cage firefox; do
  grep -qx "$package" "$KS" || fail "Required boot/kiosk package is missing: $package"
done
grep -q '^ModuleName=script$' "$THEME/feclora.plymouth" || fail "Feclora must use the script Plymouth renderer."
grep -q '^ScriptFile=feclora.script$' "$THEME/feclora.plymouth" || fail "Plymouth script entry point is not configured."
grep -q 'Image("feclora-logo.png")' "$THEME/feclora.script" || fail "Plymouth script does not load the generated Feclora PNG logo."
grep -q 'rsvg-convert .*feclora-logo.png' "$KS" || fail "Kickstart does not generate the PNG logo required by the script theme."
grep -q 'test -s "\$PLYMOUTH_THEME_DIR/feclora-logo.png"' "$KS" || fail "Kickstart does not verify the generated Plymouth logo."
grep -q 'install_items.*feclora-logo.png' "$KS" || fail "The Plymouth logo is not explicitly included in the initramfs."
grep -q 'plymouth-set-default-theme -R feclora' "$KS" || fail "Feclora is not selected and rebuilt into the initramfs."
grep -q 'add_dracutmodules.*plymouth' "$KS" || fail "Plymouth dracut module is not explicitly included."
grep -q 'rd.plymouth=1 rhgb quiet loglevel=3 vt.global_cursor_default=0' "$BUILD" || fail "Quiet graphical boot arguments are missing."
grep -q -- '--lorax-templates' "$BUILD" || fail "The ISO build does not use the hidden-menu Lorax templates."
grep -q 'set default="0"' "$BUILD" || fail "Lorax menu default is not the first entry."
grep -q 'set timeout_style=hidden' "$BUILD" || fail "Lorax menu is not configured as hidden."
grep -q 'Environment=LIBSEAT_BACKEND=logind' "$SERVICE" || fail "Cage is not pinned to the logind libseat backend."
grep -q '^exec /usr/bin/cage -- ' "$LAUNCH" || fail "Kiosk launcher must invoke Cage using supported arguments."
if grep -q 'cage -x' "$LAUNCH"; then fail "Kiosk launcher must not pass the unsupported -x option to Cage."; fi
grep -q 'WLR_RENDERER=gles2' "$LAUNCH" || fail "Cage is not configured to use the GLES2 renderer."
grep -q '^After=.*plymouth-quit-wait.service' "$SERVICE" || fail "Kiosk may take the display before Plymouth has released it."
grep -qx 'Before=graphical.target' "$SERVICE" || fail "Kiosk must be ordered before graphical.target."
grep -qx 'Wants=dbus.socket systemd-logind.service' "$SERVICE" || fail "Kiosk must explicitly pull in D-Bus and logind."
grep -qx 'PAMName=feclora-kiosk' "$SERVICE" || fail "Kiosk must use its dedicated PAM session."
grep -qx 'StandardInput=tty-fail' "$SERVICE" || fail "Kiosk must fail clearly if it cannot acquire its VT."
grep -qx 'WantedBy=graphical.target' "$SERVICE" || fail "Kiosk must start only with graphical.target."
[[ -s "$PAM" ]] || fail "Dedicated kiosk PAM configuration is missing."
grep -q 'feclora-kiosk.pam.*etc/pam.d/feclora-kiosk' "$KS" || fail "Kickstart does not install the dedicated kiosk PAM stack."
grep -q 'enable feclora-kiosk.service' "$KS" || fail "Kickstart does not enable the kiosk service."
grep -q 'enable feclora-cockpit-certificate.service feclora-cockpit-kiosk.service' "$KS" || fail "Kickstart does not enable the kiosk and its local Cockpit dependencies."
grep -q 'set-default graphical.target' "$KS" || fail "Live system default target is not graphical.target."
grep -q 'mask getty@tty1.service' "$KS" || fail "TTY1 getty is not masked for kiosk ownership."
for file in feclora.plymouth feclora.script feclora-logo-dark.svg; do
  [[ -s "$THEME/$file" ]] || fail "Plymouth theme asset is missing: $file"
done
printf 'Boot visual configuration checks passed. ISO build and BIOS/UEFI boot are not verified.\n'
