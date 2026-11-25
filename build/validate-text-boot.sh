#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
BUILD="$ROOT_DIR/build/build-iso.sh"
GTK="$ROOT_DIR/src/feclora/data/feclora-gtk.service"
TUI="$ROOT_DIR/src/feclora/data/feclora-tui.service"
READY="$ROOT_DIR/src/feclora/data/feclora-gtk-ready"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

for file in "$KS" "$BASE" "$BUILD" "$GTK" "$TUI" "$READY"; do
  [[ -s "$file" ]] || fail "Required kiosk-boot file is missing: $file"
done

for package in python3-gobject gtk4 libadwaita cage python3-textual; do
  grep -Fxq "$package" "$KS" || fail "Kickstart omits runtime package $package."
  grep -Fxq "$package" "$BASE" || fail "Base package manifest omits runtime package $package."
done
for package in plymouth plymouth-plugin-script plymouth-plugin-two-step plymouth-scripts; do
  grep -Fxq -- "-$package" "$KS" || fail "Kickstart does not exclude boot-splash package $package."
done
if grep -Eiq '^[[:space:]]*plymouth([[:space:]]|$)' "$KS"; then
  fail "Kickstart explicitly installs Plymouth."
fi
[[ ! -e "$ROOT_DIR/src/feclora/data/plymouth" ]] || fail "Obsolete splash assets remain."

# Keep Textual installed as a fallback, but make the GTK kiosk the sole tty1 boot service.
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service"' "$KS" \
  || fail "Kickstart does not retain the Textual fallback unit."
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk.service"' "$KS" \
  || fail "Kickstart does not install the GTK kiosk unit."
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk-ready"' "$KS" \
  || fail "Kickstart does not install the GTK boot readiness helper."
grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service' "$KS" \
  || fail "The Live image does not enable the GTK kiosk."
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS"; then
  fail "The Textual fallback must not be enabled as the boot UI."
fi
grep -Fq 'systemctl --root="$TARGET_ROOT" set-default multi-user.target' "$KS" \
  || fail "The appliance must retain its minimal multi-user target."
grep -Fq 'systemctl --root="$TARGET_ROOT" mask getty@tty1.service' "$KS" \
  || fail "The login prompt is not masked from tty1."
grep -Fq 'systemctl --root="$TARGET_ROOT" mask kmsconvt@tty1.service' "$KS" \
  || fail "KMS console must not compete for tty1."

grep -Fxq 'ExecStart=/usr/bin/cage -x -s -- /usr/bin/python3 -m feclora.gui_gtk' "$GTK" \
  || fail "tty1 must launch GTK inside Cage with XWayland disabled."
grep -Fxq 'PAMName=login' "$GTK" || fail "Cage must receive a logind-backed PAM session."
grep -Fxq 'TTYPath=/dev/tty1' "$GTK" || fail "GTK kiosk must own tty1."
grep -Fxq 'RuntimeDirectory=feclora-gtk' "$GTK" || fail "GTK kiosk lacks its private runtime directory."
grep -Fxq 'ExecStartPost=+/usr/libexec/feclora/feclora-gtk-ready' "$GTK" \
  || fail "GTK kiosk must report its first rendered window."
grep -Fxq 'StandardError=tty' "$GTK" || fail "GTK/Cage startup errors must remain visible on tty1."
grep -Fxq 'feclora-gtk.service' "$ROOT_DIR/src/feclora/data/feclora-local-operation-recovery.service" \
  || fail "Durable operation recovery must precede GTK startup."
grep -Fq 'console=tty0 rd.systemd.show_status=1 systemd.show_status=1' "$BUILD" \
  || fail "ISO must retain visible kernel and systemd boot messages."
grep -Fq 'self.window.connect("map", lambda _window: GLib.idle_add(self._report_boot_rendered))' "$ROOT_DIR/src/feclora/gui_gtk.py" \
  || fail "GTK must report readiness after its welcome window is mapped."
grep -Fq 'Path("/run/feclora-gtk/ready")' "$ROOT_DIR/src/feclora/gui_gtk.py" \
  || fail "GTK readiness marker does not match the systemd runtime directory."
grep -Fq 'FECLORA_BOOT_SMOKE rendered' "$READY" \
  || fail "GTK readiness helper does not report its rendered window."
grep -Fq 'virtio-serial-pci' "$ROOT_DIR/tests/vm/run-boot-smoke.py" \
  || fail "QEMU smoke test lacks its guest readiness channel."
grep -Fq '"-vga"' "$ROOT_DIR/tests/vm/run-boot-smoke.py" \
  && grep -Fq '"virtio"' "$ROOT_DIR/tests/vm/run-boot-smoke.py" \
  || fail "QEMU smoke test does not expose a virtual DRM-capable display."

if grep -Eiq '(^|[[:space:]])(cockpit[^[:space:]]*|weston|firefox|xorg-x11-server-Xorg|xorg-x11-server-Xwayland)([[:space:]]|$)' "$KS" "$BASE"; then
  fail "The boot package configuration includes an unrelated desktop or X11 stack."
fi
if grep -Eiq 'cockpit|weston|firefox|webui|xorg-x11-server-Xorg|xorg-x11-server-Xwayland' "$KS" "$GTK"; then
  fail "GTK kiosk boot configuration references a desktop, browser or X11 stack."
fi

if (( ERRORS > 0 )); then
  printf 'GTK Wayland kiosk boot validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'GTK Wayland kiosk tty1 boot configuration checks passed.\n'
