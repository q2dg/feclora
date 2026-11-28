#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
BUILD="$ROOT_DIR/build/build-iso.sh"
TUI="$ROOT_DIR/src/feclora/data/feclora-tui.service"
READY="$ROOT_DIR/src/feclora/data/feclora-tui-ready"
TERMINAL="$ROOT_DIR/src/feclora/data/feclora-root-terminal.service"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

for file in "$KS" "$BASE" "$BUILD" "$TUI" "$READY" "$TERMINAL"; do
  [[ -s "$file" ]] || fail "Required Textual boot file is missing: $file"
done

for file in "$KS" "$BASE"; do
  grep -Fxq 'python3-textual' "$file" || fail "$file must include python3-textual."
  if grep -Fxq 'python3-gobject' "$file" || grep -Fxq 'python3-cairo' "$file"; then
    fail "$file must not pull stock Cairo/X11 dependencies into the Textual image before custom Cairo RPMs are admitted."
  fi
  if grep -Eq '^(weston|weston-libs|gtk4|libadwaita|openbox|cage|xorg-x11-server-Xorg|xorg-x11-server-Xwayland)$' "$file"; then
    fail "$file includes an unverified graphical runtime package."
  fi
done

# shellcheck disable=SC2016
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service" "$TARGET_ROOT/etc/systemd/system/feclora-tui.service"' "$KS" || fail "Kickstart must install the Textual tty1 unit."
# shellcheck disable=SC2016
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui-ready" "$TARGET_ROOT/usr/libexec/feclora/feclora-tui-ready"' "$KS" || fail "Kickstart must install the Textual readiness helper."
# shellcheck disable=SC2016
grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service feclora-root-terminal.service' "$KS" || fail "Textual and tty2 maintenance must be enabled."
# shellcheck disable=SC2016
if grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-gtk.service' "$KS"; then
  fail "GTK must not become production before package, parity and BIOS/UEFI acceptance."
fi

grep -Fxq 'ExecStart=/usr/bin/python3 -m feclora.tui' "$TUI" || fail "Textual service must run feclora.tui."
grep -Fxq 'TTYPath=/dev/tty1' "$TUI" || fail "Textual must own tty1."
grep -Fxq 'Conflicts=getty@tty1.service kmsconvt@tty1.service' "$TUI" || fail "Textual must exclude getty and KMSCON from tty1."
grep -Fxq 'ExecStartPost=+/usr/libexec/feclora/feclora-tui-ready' "$TUI" || fail "Textual must report its first rendered screen."
grep -Fq 'FECLORA_BOOT_SMOKE rendered' "$READY" || fail "Textual readiness marker is missing."
grep -Fxq 'TTYPath=/dev/tty2' "$TERMINAL" || fail "The maintenance shell must own tty2."
grep -Fxq 'Conflicts=getty@tty2.service kmsconvt@tty2.service' "$TERMINAL" || fail "The maintenance shell must exclude getty and KMSCON from tty2."

grep -Fq 'mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service' "$KS" || fail "KMSCON must not own appliance VTs."
grep -Fq 'mask getty@tty1.service getty@tty2.service' "$KS" || fail "Getty must not compete for tty1 or tty2."
# shellcheck disable=SC2016
grep -Fq 'systemctl --root="$TARGET_ROOT" set-default multi-user.target' "$KS" || fail "The appliance must use the minimal multi-user target."
grep -Fq 'console=tty0 rd.systemd.show_status=1 systemd.show_status=1' "$BUILD" || fail "Kernel and systemd boot messages must remain visible."

printf 'Textual production boot configuration verified; GTK remains staged and disabled.\n'
