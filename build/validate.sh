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

# Core build inputs and application payload.
for file in \
  build/build-iso.sh build/build-webui.sh build/preflight.sh \
  kickstart/feclora-live.ks webui/package.json webui/package-lock.json \
  webui/src/App.jsx webui/src/api.js webui/src/i18n.js \
  src/feclora/webapi.py src/feclora/data/feclora-cockpit-kiosk.service \
  src/feclora/data/feclora-kiosk.service src/feclora/data/feclora-kiosk-launch \
  src/feclora/data/feclora-kiosk.pam build/validate-boot-visuals.sh \\
  src/feclora/data/feclora-kiosk-firefox-policies.json \
  src/feclora/data/feclora-root-terminal.service \
  src/feclora/data/feclora-kiosk-return.service \
  src/feclora/data/plymouth/feclora.plymouth \
  src/feclora/data/plymouth/feclora.script \
  build/check_docs.py; do
  require_file "$file"
done

# Validate the supported Fedora baseline and reproducible build configuration.
require_text '^#version=F45$' kickstart/feclora-live.ks "Kickstart must target Fedora 45."
require_text '^GRUB_DEFAULT=0$' kickstart/feclora-live.ks "GRUB must select the first entry."
require_text '^GRUB_TIMEOUT_STYLE=hidden$' kickstart/feclora-live.ks "GRUB menu must be hidden."
require_text 'FECLORA_BUILD_RAM' build/build-iso.sh "ISO build RAM must be configurable."
require_text 'FECLORA_BUILD_VCPUS' build/build-iso.sh "ISO build vCPU count must be configurable."
require_text 'LOCK_FINGERPRINT' build/build-webui.sh "Frontend build must fingerprint locked dependencies."
require_text 'npm ci --no-audit --no-fund' build/build-webui.sh "Frontend build must use reproducible npm ci."

# Keep the kiosk local-only and unprivileged, while Cockpit's local session is
# deliberately isolated on IPv4 loopback.
require_text '^ExecStart=/usr/libexec/cockpit-ws --address 127\.0\.0\.1 --port 9091 --local-session /usr/libexec/cockpit-bridge$' src/feclora/data/feclora-cockpit-kiosk.service "Passwordless Cockpit must use the loopback-only local session."
require_text '^IPAddressDeny=any$' src/feclora/data/feclora-kiosk.service "Firefox kiosk must deny non-loopback network access."
require_text '^IPAddressAllow=127\.0\.0\.1/32$' src/feclora/data/feclora-kiosk.service "Firefox kiosk must allow IPv4 loopback."
require_text '^IPAddressAllow=::1/128$' src/feclora/data/feclora-kiosk.service "Firefox kiosk must allow IPv6 loopback."
require_text 'http://127\.0\.0\.1:9091/cockpit/@localhost/feclora/index\.html' src/feclora/data/feclora-kiosk-launch "Kiosk launcher must open the local Feclora Cockpit application."
require_text 'languageConfirmed' webui/src/App.jsx "The first visible screen must be the language selector."
require_text 'open_root_terminal' webui/src/App.jsx "Language selector must expose the root-terminal action."
require_text 'open_root_terminal' webui/src/api.js "Frontend API must expose the root-terminal action."
require_text 'open_root_terminal' kickstart/feclora-live.ks "Installed Cockpit API wrapper must allow the root-terminal action."
require_text 'open_root_terminal' src/feclora/webapi.py "Privileged API must implement the root-terminal action."
require_text 'feclora-root-terminal\.service' src/feclora/webapi.py "Privileged API must request only the fixed root-terminal unit."
require_text 'feclora-kiosk-return\.service' src/feclora/data/feclora-root-terminal.service "Root shell exit must restore the kiosk."
require_text '^User=root$' src/feclora/data/feclora-root-terminal.service "Root terminal must run as root."
require_text '^TTYPath=/dev/tty1$' src/feclora/data/feclora-root-terminal.service "Root terminal must use the physical kiosk display."
require_text '^Conflicts=feclora-cockpit-kiosk\.service feclora-kiosk\.service$' src/feclora/data/feclora-root-terminal.service "Root terminal must stop the graphical kiosk while active."

# Validate the complete Plymouth and graphical-session handoff configuration.
if ! bash "$ROOT_DIR/build/validate-boot-visuals.sh"; then
  fail "Boot visual and kiosk session validation failed."
fi

# Shell syntax and Python correctness.
while IFS= read -r -d '' script; do
  bash -n "$script" || fail "Bash syntax check failed: $script"
done < <(find "$ROOT_DIR/build" -maxdepth 1 -type f -name '*.sh' -print0)
bash -n "$ROOT_DIR/src/feclora/data/feclora-kiosk-launch" || fail "Kiosk launcher has invalid Bash syntax."
python3 -m compileall -q "$ROOT_DIR/src" "$ROOT_DIR/tests" || fail "Python compilation failed."

# Run the complete test suite once; do not report success if any test fails.
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
