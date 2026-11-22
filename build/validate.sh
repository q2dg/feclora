#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ERRORS=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  ERRORS=$((ERRORS + 1))
}

require_file() {
  [[ -s "$ROOT_DIR/$1" ]] || fail "Required file is missing or empty: $1"
}

require_text() {
  local pattern="$1" file="$2" message="$3"
  grep -Eq -- "$pattern" "$ROOT_DIR/$file" || fail "$message"
}

for file in \
  build/build-iso.sh build/preflight.sh kickstart/feclora-live.ks \
  packages/base.txt requirements-test.txt src/feclora/tui.py \
  src/feclora/tui_api.py src/feclora/api.py \
  src/feclora/data/feclora-api src/feclora/data/feclora-tui.service \
  src/feclora/data/feclora-tui-ready src/feclora/data/feclora-root-terminal.service \
  src/feclora/data/feclora-local-operation-recovery.service \
  build/validate-text-boot.sh build/verify-iso-text-boot.sh \
  build/check_docs.py; do
  require_file "$file"
done

require_text '^#version=F45$' kickstart/feclora-live.ks "Kickstart must target Fedora 45."
require_text '^python3-textual$' packages/base.txt "The Live image must install Textual."
require_text '^textual==8\.1\.1$' requirements-test.txt "TUI tests must use the runtime Textual version."
require_text 'create_subprocess_exec' src/feclora/tui_api.py "The TUI must invoke the API helper without a shell."
if grep -Fq 'create_subprocess_shell' "$ROOT_DIR/src/feclora/tui_api.py"; then
  fail "TUI API requests must not use a command shell."
fi

require_text '^User=feclora$' src/feclora/data/feclora-tui.service "The TUI must run as its unprivileged appliance user."
require_text '^ExecStart=/usr/bin/python3 -m feclora\.tui$' src/feclora/data/feclora-tui.service "tty1 must launch the Textual application."
require_text '^ExecStartPost=\+/usr/libexec/feclora/feclora-tui-ready$' src/feclora/data/feclora-tui.service "The TUI unit must report the QEMU smoke-test readiness event."
require_text 'feclora ALL=\(root\) NOPASSWD: /usr/libexec/feclora/feclora-api \*' kickstart/feclora-live.ks "Passwordless root access must be limited to the validated API helper."
if grep -Eq '^(NoNewPrivileges=true|ProtectSystem=full)$' "$ROOT_DIR/src/feclora/data/feclora-tui.service"; then
  fail "The TUI service must allow its scoped sudo helper to perform privileged appliance operations."
fi
require_text 'set-default multi-user\.target' kickstart/feclora-live.ks "The default boot target must not require a graphical desktop."
require_text 'mask getty@tty1\.service' kickstart/feclora-live.ks "tty1 must be reserved for the Textual interface."
require_text '^TTYPath=/dev/tty2$' src/feclora/data/feclora-root-terminal.service "The diagnostic root shell must use tty2."
require_text 'feclora-tui\.service' src/feclora/data/feclora-local-operation-recovery.service "Durable operations must recover before the TUI starts."
require_text 'FECLORA_SELINUX_PERMISSIVE:-1' build/build-iso.sh "SELinux permissive mode must remain the diagnostic build default."
require_text 'mkksiso --cmdline selinux=0' build/build-iso.sh "Only the temporary Anaconda build VM may disable SELinux."

if grep -Eiq '(^|[[:space:]])(cockpit[^[:space:]]*|weston|firefox)([[:space:]]|$)' \
  "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/kickstart/feclora-live.ks"; then
  fail "The Live image package set must not include Cockpit, Weston or Firefox."
fi
if grep -Eiq 'cockpit|weston|firefox|webui' "$ROOT_DIR/build/build-iso.sh"; then
  fail "ISO construction must stage only the Textual application."
fi

if ! python3 - "$ROOT_DIR" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
base = {
    line.strip() for line in (root / "packages/base.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
kickstart = (root / "kickstart/feclora-live.ks").read_text(encoding="utf-8")
match = re.search(r"(?ms)^%packages[^\n]*\n(.*?)^%end\s*$", kickstart)
if match is None:
    raise SystemExit("Kickstart %packages block was not found.")
ks = {
    line.strip() for line in match.group(1).splitlines()
    if line.strip() and not line.lstrip().startswith(("#", "@", "-"))
}
if base != ks:
    raise SystemExit(
        f"Package manifests differ. Missing from base.txt: {sorted(ks - base)}; "
        f"only in base.txt: {sorted(base - ks)}"
    )
exclusions = {
    line.strip()[1:] for line in match.group(1).splitlines()
    if line.strip().startswith("-")
}
expected_exclusions = {
    "plymouth", "plymouth-plugin-script", "plymouth-plugin-two-step", "plymouth-scripts"
}
if exclusions != expected_exclusions:
    raise SystemExit(
        f"Kickstart splash-package exclusions differ. Expected {sorted(expected_exclusions)}; "
        f"found {sorted(exclusions)}."
    )
if "openssh-clients" not in ks:
    raise SystemExit("Kickstart must install openssh-clients.")
PY
then
  fail "The package manifest and Kickstart package set must match."
fi

if ! bash "$ROOT_DIR/build/validate-text-boot.sh"; then
  fail "Text-only boot configuration validation failed."
fi

while IFS= read -r -d '' script; do
  bash -n "$script" || fail "Bash syntax check failed: $script"
done < <(find "$ROOT_DIR/build" -maxdepth 1 -type f -name '*.sh' -print0)
bash -n "$ROOT_DIR/kickstart/feclora-live.ks" \
  || fail "Kickstart contains invalid embedded shell syntax."
bash -n "$ROOT_DIR/src/feclora/data/feclora-api" || fail "Privileged API helper has invalid shell syntax."
python3 -m compileall -q "$ROOT_DIR/src" "$ROOT_DIR/tests" || fail "Python compilation failed."

if ! PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_*.py'; then
  fail "Python unit tests failed."
fi
if ! python3 "$ROOT_DIR/build/check_docs.py"; then
  fail "Documentation links and guide assets failed validation."
fi

if (( ERRORS > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$ERRORS" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'
