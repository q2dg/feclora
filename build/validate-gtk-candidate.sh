#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
UNIT="$ROOT_DIR/src/feclora/data/feclora-gtk.service"
GUI="$ROOT_DIR/src/feclora/gui_gtk.py"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

for file in "$KS" "$BASE" "$UNIT" "$GUI" "$ROOT_DIR/build/verify-wayland-rpms.sh"; do
  [[ -s "$file" ]] || fail "Required GTK candidate file is missing: $file"
done

grep -Fxq 'Environment=GDK_BACKEND=wayland' "$UNIT" || fail "GTK must force the native Wayland backend."
grep -Fxq 'UnsetEnvironment=DISPLAY XAUTHORITY WAYLAND_DISPLAY' "$UNIT" || fail "GTK service must clear inherited X11 and stale Wayland display variables before Weston starts."
grep -Fq 'ExecStart=/usr/bin/weston --no-config -B drm --shell=kiosk-shell.so --idle-time=0 -- /usr/bin/python3 -m feclora.gui_gtk' "$UNIT" || fail "Candidate must use Weston DRM/KMS kiosk-shell and --no-config."
if grep -q -- '--xwayland' "$UNIT"; then fail "Weston must not offer XWayland."; fi
grep -Fq 'os.environ["GDK_BACKEND"] = "wayland"' "$GUI" || fail "GTK must force GDK Wayland."
grep -Fq 'os.environ.pop("DISPLAY", None)' "$GUI" || fail "GTK must remove DISPLAY."
grep -Fq 'if not os.environ.get("WAYLAND_DISPLAY")' "$GUI" || fail "GTK must fail closed without WAYLAND_DISPLAY."
# shellcheck disable=SC2016 -- match literal source text, not an expansion
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service' "$KS"; then
  fail "The GTK candidate is not eligible for production activation yet."
fi
# shellcheck disable=SC2016 -- match literal source text, not an expansion
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk.service"' "$KS" || fail "GTK candidate unit must remain staged for testing."

printf 'GTK candidate is Wayland-only by configuration and is not enabled in production.\n'
