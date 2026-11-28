#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
CANDIDATE="$ROOT_DIR/packages/wayland-candidate-runtime.txt"
UNIT="$ROOT_DIR/src/feclora/data/feclora-gtk.service"
GUI="$ROOT_DIR/src/feclora/gui_gtk.py"
PATCHER="$ROOT_DIR/build/patch-fedora-wayland-spec.py"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

for file in "$KS" "$BASE" "$CANDIDATE" "$UNIT" "$GUI" "$PATCHER" "$ROOT_DIR/build/verify-wayland-rpms.sh"; do
  [[ -s "$file" ]] || fail "Required GTK candidate file is missing: $file"
done

grep -Fxq 'python3-gobject' "$CANDIDATE" || fail "GTK candidate must use Fedora's system PyGObject package."
grep -Fxq 'python3-cairo' "$CANDIDATE" || fail "GTK candidate must use Fedora's system Cairo bindings."
for package in cairo cairo-gobject weston weston-libs gtk4 libadwaita; do
  grep -Fxq "$package" "$CANDIDATE" || fail "GTK candidate manifest is missing custom RPM package $package."
done
if grep -Fxq 'python3-gobject' "$BASE" || grep -Fxq 'python3-gobject' "$KS"; then
  fail "PyGObject must remain staged until the custom X11-free Cairo RPMs are built and verified."
fi
grep -Fxq 'Environment=GDK_BACKEND=wayland' "$UNIT" || fail "GTK must force the native Wayland backend."
grep -Fxq 'Environment=GSK_RENDERER=cairo' "$UNIT" || fail "GTK must use the Cairo renderer without GL/Vulkan runtime dependencies."
grep -Fq '"-Drenderer-gl=false"' "$PATCHER" || fail "Weston GL renderer must be disabled to avoid Mesa X11 dependencies."
grep -Fq '"-Dxwayland=false"' "$PATCHER" || fail "Weston XWayland support must be disabled at build time."
grep -Fq '"-Dbackend-x11=false"' "$PATCHER" || fail "Weston X11 backend must be disabled at build time."
grep -Fq '"-Dbackend-drm=true"' "$PATCHER" || fail "Weston DRM/KMS backend must remain enabled."
grep -Fq '"-Dshell-kiosk=true"' "$PATCHER" || fail "Weston kiosk-shell must remain enabled."
grep -Fq '"-Dsystemd=true"' "$PATCHER" || fail "Weston systemd/logind integration must remain enabled."
grep -Fq '"-Dx11-backend=false"' "$PATCHER" || fail "GTK GDK X11 backend must be disabled."
grep -Fq '"-Dwayland-backend=true"' "$PATCHER" || fail "GTK GDK Wayland backend must remain enabled."
grep -Fq '"-Dxlib=disabled"' "$PATCHER" || fail "Cairo Xlib surfaces must be disabled."
grep -Fq '"-Dxcb=disabled"' "$PATCHER" || fail "Cairo XCB surfaces must be disabled."
grep -Fq '"-Dxlib-xcb=disabled"' "$PATCHER" || fail "Cairo Xlib-XCB surfaces must be disabled."
grep -Fq '"-Drenderer-vulkan=false"' "$PATCHER" || fail "Weston Vulkan renderer must be disabled in the software-only kiosk."
grep -Fq '"-Dvulkan=disabled"' "$PATCHER" || fail "GTK Vulkan support must be disabled."
grep -Fxq 'UnsetEnvironment=DISPLAY XAUTHORITY WAYLAND_DISPLAY' "$UNIT" || fail "GTK service must clear inherited X11 and stale Wayland display variables before Weston starts."
grep -Fq 'ExecStart=/usr/bin/weston --no-config -B drm --renderer=pixman --shell=kiosk-shell.so --idle-time=0 -- /usr/bin/python3 -m feclora.gui_gtk' "$UNIT" || fail "Candidate must use Weston DRM/KMS kiosk-shell and --no-config."
if grep -q -- '--xwayland' "$UNIT"; then fail "Weston must not offer XWayland."; fi
grep -Fq 'os.environ["GDK_BACKEND"] = "wayland"' "$GUI" || fail "GTK must force GDK Wayland."
grep -Fq 'os.environ["GSK_RENDERER"] = "cairo"' "$GUI" || fail "GTK must force the Cairo GSK renderer."
grep -Fq 'os.environ.pop("DISPLAY", None)' "$GUI" || fail "GTK must remove DISPLAY."
grep -Fq 'if not os.environ.get("WAYLAND_DISPLAY")' "$GUI" || fail "GTK must fail closed without WAYLAND_DISPLAY."
# shellcheck disable=SC2016
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service' "$KS"; then
  fail "The GTK candidate is not eligible for production activation yet."
fi
# shellcheck disable=SC2016
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk.service"' "$KS" || fail "GTK candidate unit must remain staged for testing."

printf 'GTK candidate is Wayland-only by configuration and is not enabled in production.\n'
