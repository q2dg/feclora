#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BUILD="$ROOT_DIR/build/build-iso.sh"
SERVICE="$ROOT_DIR/src/feclora/data/feclora-kiosk.service"
THEME="$ROOT_DIR/src/feclora/data/plymouth"
fail() { echo "BOOT VISUAL VALIDATION ERROR: $*" >&2; exit 1; }

grep -q '^plymouth$' "$KS" || fail "Plymouth package is not installed."
grep -q '^librsvg2-toolsgrep -q 'plymouth-set-default-theme -R feclora' "$KS" || fail "Feclora is not selected as the initramfs Plymouth theme."
grep -q 'rd.plymouth=1 rhgb quiet loglevel=3 vt.global_cursor_default=0' "$BUILD" || fail "Quiet graphical boot arguments are missing."
grep -q -- '--lorax-templates' "$BUILD" || fail "The ISO build does not use the hidden-menu Lorax templates."
grep -q 'set default="0"' "$BUILD" || fail "Lorax menu default is not the first entry."
grep -q 'set timeout_style=hidden' "$BUILD" || fail "Lorax menu is not configured as hidden."
grep -q 'Environment=LIBSEAT_BACKEND=logind' "$SERVICE" || fail "Cage is not pinned to the logind libseat backend."
grep -q 'cage -x --' "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" || fail "Cage is not configured to disable XWayland."
grep -q 'WLR_RENDERER=gles2' "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" || fail "Cage is not configured to use the GLES2 renderer."
grep -q 'Before=plymouth-quit.service' "$SERVICE" || fail "The kiosk is not ordered before Plymouth exits."
for file in feclora.plymouth feclora.script feclora-logo-dark.svg; do
  [[ -s "$THEME/$file" ]] || fail "Plymouth theme asset is missing: $file"
done
printf 'Boot visual configuration checks passed. ISO build and BIOS/UEFI boot are not verified.\n'
 "$KS" || fail "SVG-to-PNG conversion tool is not installed."
grep -q 'ModuleName=two-step' "$THEME/feclora.plymouth" || fail "Feclora is not using the standard two-step Plymouth renderer."
grep -q 'watermark.png' "$KS" || fail "Feclora logo is not installed as the Plymouth watermark."
grep -q 'plymouth-set-default-theme -R feclora' "$KS" || fail "Feclora is not selected as the initramfs Plymouth theme."
grep -q 'rd.plymouth=1' "$BUILD" || fail "Live boot arguments do not enable Plymouth."
grep -q -- '--lorax-templates' "$BUILD" || fail "The ISO build does not use the hidden-menu Lorax templates."
grep -q 'set default="0"' "$BUILD" || fail "Lorax menu default is not the first entry."
grep -q 'set timeout_style=hidden' "$BUILD" || fail "Lorax menu is not configured as hidden."
grep -q 'Environment=LIBSEAT_BACKEND=logind' "$SERVICE" || fail "Cage is not pinned to the logind libseat backend."
for file in feclora.plymouth feclora.script feclora-logo-dark.svg; do
  [[ -s "$THEME/$file" ]] || fail "Plymouth theme asset is missing: $file"
done
printf 'Boot visual configuration checks passed. ISO build and BIOS/UEFI boot are not verified.\n'
