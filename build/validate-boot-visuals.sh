#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BUILD="$ROOT_DIR/build/build-iso.sh"
SERVICE="$ROOT_DIR/src/feclora/data/feclora-kiosk.service"
LAUNCH="$ROOT_DIR/src/feclora/data/feclora-kiosk-launch"
THEME="$ROOT_DIR/src/feclora/data/plymouth"
fail() { echo "BOOT VISUAL VALIDATION ERROR: $*" >&2; exit 1; }

for package in plymouth plymouth-plugin-script librsvg2-tools cage firefox; do
  grep -qx "$package" "$KS" || fail "Required boot/kiosk package is missing: $package"
done
grep -q '^ModuleName=script$' "$THEME/feclora.plymouth" || fail "Feclora must use the script Plymouth renderer."
grep -q '^ScriptFile=feclora.script$' "$THEME/feclora.plymouth" || fail "Plymouth script entry point is not configured."
grep -q 'Image("feclora-logo.png")' "$THEME/feclora.script" || fail "Plymouth script does not load the generated Feclora PNG logo."
grep -q 'rsvg-convert .*feclora-logo.png' "$KS" || fail "Kickstart does not generate the PNG logo required by the script theme."
grep -q 'plymouth-set-default-theme -R feclora' "$KS" || fail "Feclora is not selected and rebuilt into the initramfs."
grep -q 'add_dracutmodules.*plymouth' "$KS" || fail "Plymouth dracut module is not explicitly included."
grep -q 'rd.plymouth=1 rhgb quiet loglevel=3 vt.global_cursor_default=0' "$BUILD" || fail "Quiet graphical boot arguments are missing."
grep -q -- '--lorax-templates' "$BUILD" || fail "The ISO build does not use the hidden-menu Lorax templates."
grep -q 'set default="0"' "$BUILD" || fail "Lorax menu default is not the first entry."
grep -q 'set timeout_style=hidden' "$BUILD" || fail "Lorax menu is not configured as hidden."
grep -q 'Environment=LIBSEAT_BACKEND=logind' "$SERVICE" || fail "Cage is not pinned to the logind libseat backend."
grep -q 'cage -x --' "$LAUNCH" || fail "Cage is not configured to disable XWayland."
grep -q 'WLR_RENDERER=gles2' "$LAUNCH" || fail "Cage is not configured to use the GLES2 renderer."
grep -q '^WantedBy=graphical.target$' "$SERVICE" || fail "Kiosk service is not enabled for graphical.target."
grep -q 'enable feclora-cockpit-certificate.service feclora-cockpit-kiosk.service feclora-kiosk.service' "$KS" || fail "Kickstart does not enable the kiosk and its local Cockpit dependencies."
grep -q 'set-default graphical.target' "$KS" || fail "Live system default target is not graphical.target."
grep -q 'mask getty@tty1.service' "$KS" || fail "TTY1 getty is not masked for kiosk ownership."
for file in feclora.plymouth feclora.script feclora-logo-dark.svg; do
  [[ -s "$THEME/$file" ]] || fail "Plymouth theme asset is missing: $file"
done
printf 'Boot visual configuration checks passed. ISO build and BIOS/UEFI boot are not verified.\n'
