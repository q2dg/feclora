#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
BUILD="$ROOT_DIR/build/build-iso.sh"
GTK="$ROOT_DIR/src/feclora/data/feclora-gtk.service"
READY="$ROOT_DIR/src/feclora/data/feclora-gtk-ready"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

for file in "$KS" "$BASE" "$BUILD" "$GTK" "$READY"; do
  [[ -s "$file" ]] || fail "Required text-boot file is missing: $file"
done

grep -Fq 'python3-textual' "$KS" || fail "Kickstart does not retain the Textual fallback."
for package in python3-gobject gtk4 libadwaita cage; do
  grep -Fxq "$package" "$KS" || fail "Kickstart does not install GTK kiosk dependency $package."
done
for package in python3-gobject gtk4 libadwaita cage; do
  grep -Fxq "$package" "$BASE" || fail "Base package manifest omits GTK kiosk dependency $package."
done
for package in plymouth plymouth-plugin-script plymouth-plugin-two-step plymouth-scripts; do
  grep -Fxq -- "-$package" "$KS" \
    || fail "Kickstart does not explicitly exclude the boot-splash package $package."
done
if grep -Eiq '^[[:space:]]*plymouth([[:space:]]|$)' "$KS"; then
  fail "Kickstart explicitly installs the boot-splash package."
fi
[[ ! -e "$ROOT_DIR/src/feclora/data/plymouth" ]] \
  || fail "Obsolete Feclora boot-splash assets remain in the application payload."
# shellcheck disable=SC2016 # Match literal shell source; do not expand TARGET_ROOT here.
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service"' "$KS" \
  || fail "Kickstart does not install the Textual systemd service."
# shellcheck disable=SC2016 # Match literal shell source; do not expand TARGET_ROOT here.
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui-ready"' "$KS" \
  || fail "Kickstart does not install the QEMU boot readiness helper."
# shellcheck disable=SC2016 # Match literal shell source; do not expand TARGET_ROOT here.
grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS" \
  || fail "The Live image does not enable the TUI service."
# shellcheck disable=SC2016 # Match literal shell source; do not expand TARGET_ROOT here.
grep -Fq 'systemctl --root="$TARGET_ROOT" set-default multi-user.target' "$KS" \
  || fail "The Live image does not select the text-mode systemd target."
# shellcheck disable=SC2016 # Match literal shell source; do not expand TARGET_ROOT here.
grep -Fq 'systemctl --root="$TARGET_ROOT" mask getty@tty1.service' "$KS" \
  || fail "The system login prompt is not masked from the appliance TUI."
# shellcheck disable=SC2016 # Match literal shell source; do not expand TARGET_ROOT here.
grep -Fq 'systemctl --root="$TARGET_ROOT" mask kmsconvt@tty1.service' "$KS" \
  || fail "The KMS console must not compete with the appliance TUI on tty1."
grep -Fq 'feclora ALL=(root) NOPASSWD: /usr/libexec/feclora/feclora-api *' "$KS" \
  || fail "The unprivileged interface lacks its restricted API authorization."
grep -Fxq 'ExecStart=/usr/bin/python3 -m feclora.tui' "$TUI" \
  || fail "The tty1 service does not start Textual."
grep -Fxq 'StandardError=tty' "$GTK" \
  || fail "TUI startup errors must be visible on tty1."
grep -Fxq 'ExecStartPre=+/usr/bin/echo Starting Feclora Textual interface' "$TUI" \
  || fail "The TUI service must visibly announce its startup on tty1."
if grep -Eiq 'plymouth|rhgb|quiet|splash' "$GTK"; then
  fail "The GTK kiosk service still depends on boot-splash resources."
fi
grep -Fq 'console=tty0 rd.systemd.show_status=1 systemd.show_status=1' "$BUILD" \
  || fail "The ISO does not force visible text-mode boot status on the virtual console."
grep -Fxq 'RuntimeDirectory=feclora-tui' "$TUI" \
  || fail "The TUI service does not create its private startup marker directory."
grep -Fxq 'ExecStartPost=+/usr/libexec/feclora/feclora-tui-ready' "$TUI" \
  || fail "The TUI service must report its initial rendered screen."
grep -Fq 'FECLORA_BOOT_SMOKE ready' "$READY" \
  && fail "The readiness helper reports process startup instead of a rendered screen."
grep -Fq 'FECLORA_BOOT_SMOKE rendered' "$READY" \
  || fail "The readiness helper does not report a rendered TUI screen."
grep -Fq 'self.call_after_refresh(self._report_boot_rendered)' "$ROOT_DIR/src/feclora/tui.py" \
  || fail "The TUI does not report readiness after its first render."
grep -Fq 'RuntimeDirectoryMode=0700' "$GTK" \
  || fail "The TUI startup marker directory is not private."
grep -Fq 'org.feclora.boot-smoke' "$ROOT_DIR/tests/vm/run-boot-smoke.py" \
  || fail "The QEMU smoke test lacks its guest readiness channel."

if grep -Eiq '(^|[[:space:]])(cockpit[^[:space:]]*|weston|firefox|xorg-x11-server-Xorg|xorg-x11-server-Xwayland)([[:space:]]|$)' "$KS" "$BASE"; then
  fail "The boot package configuration still references the removed graphical stack."
fi
if grep -Eiq 'cockpit|weston|firefox|webui|xorg-x11-server-Xorg|xorg-x11-server-Xwayland' "$KS" "$GTK"; then
  fail "GTK kiosk boot configuration references a desktop, browser or X11 stack."
fi
if (( ERRORS > 0 )); then
  printf 'Textual boot configuration validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'GTK Wayland kiosk tty1 boot configuration checks passed.\n'
