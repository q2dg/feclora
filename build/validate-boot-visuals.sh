#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
KS="$ROOT_DIR/kickstart/feclora-live.ks"
BASE="$ROOT_DIR/packages/base.txt"
TUI="$ROOT_DIR/src/feclora/data/feclora-tui.service"
READY="$ROOT_DIR/src/feclora/data/feclora-tui-ready"
PLYMOUTH="$ROOT_DIR/src/feclora/data/plymouth"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

for file in \
  "$KS" "$BASE" "$TUI" "$READY" \
  "$PLYMOUTH/feclora.plymouth" "$PLYMOUTH/feclora.script" \
  "$PLYMOUTH/feclora-logo-dark.svg"; do
  [[ -s "$file" ]] || fail "Required TUI/Plymouth boot file is missing: $file"
done

grep -Fq 'python3-textual' "$KS" || fail "Kickstart does not install python3-textual."
grep -Fq 'install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service"' "$KS" \
  || fail "Kickstart does not install the Textual systemd service."
grep -Fq 'install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui-ready"' "$KS" \
  || fail "Kickstart does not install the QEMU boot readiness helper."
grep -Fq 'systemctl --root="$TARGET_ROOT" enable feclora-tui.service' "$KS" \
  || fail "The Live image does not enable the TUI service."
grep -Fq 'systemctl --root="$TARGET_ROOT" set-default multi-user.target' "$KS" \
  || fail "The Live image does not select the text-mode systemd target."
grep -Fq 'systemctl --root="$TARGET_ROOT" mask getty@tty1.service' "$KS" \
  || fail "The system login prompt is not masked from the appliance TUI."
grep -Fq 'systemctl --root="$TARGET_ROOT" mask kmsconvt@tty1.service' "$KS" \
  || fail "The KMS console must not compete with the appliance TUI on tty1."
grep -Fq 'feclora ALL=(root) NOPASSWD: /usr/libexec/feclora/feclora-api *' "$KS" \
  || fail "The unprivileged interface lacks its restricted API authorization."
grep -Fxq 'ExecStart=/usr/bin/python3 -m feclora.tui' "$TUI" \
  || fail "The tty1 service does not start Textual."
grep -Fxq 'RuntimeDirectory=feclora-tui' "$TUI" \
  || fail "The TUI service does not create its private startup marker directory."
grep -Fxq 'ExecStartPost=-+/usr/bin/plymouth quit' "$TUI" \
  || fail "Plymouth must be dismissed for the terminal interface."
grep -Fxq 'ExecStartPost=+/usr/libexec/feclora/feclora-tui-ready' "$TUI" \
  || fail "The TUI service must report boot readiness after Plymouth is dismissed."
grep -Fq 'FECLORA_BOOT_SMOKE ready' "$READY" \
  && fail "The readiness helper reports process startup instead of a rendered screen."
grep -Fq 'FECLORA_BOOT_SMOKE rendered' "$READY" \
  || fail "The readiness helper does not report a rendered TUI screen."
grep -Fq 'self.call_after_refresh(self._report_boot_rendered)' "$ROOT_DIR/src/feclora/tui.py" \
  || fail "The TUI does not report readiness after its first render."
grep -Fq 'RuntimeDirectoryMode=0700' "$TUI" \
  || fail "The TUI startup marker directory is not private."
grep -Fq 'org.feclora.boot-smoke' "$ROOT_DIR/tests/vm/run-boot-smoke.py" \
  || fail "The QEMU smoke test lacks its guest readiness channel."

if grep -Eiq '(^|[[:space:]])(cockpit[^[:space:]]*|weston|firefox)([[:space:]]|$)' "$KS" "$BASE"; then
  fail "The boot package configuration still references the removed graphical stack."
fi
if grep -Eiq 'cockpit|weston|firefox|webui' "$KS" "$TUI"; then
  fail "Textual boot configuration still references Cockpit, Weston, Firefox or the web UI."
fi

if (( ERRORS > 0 )); then
  printf 'Textual boot configuration validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'Textual tty1 and Plymouth boot configuration checks passed.\n'
