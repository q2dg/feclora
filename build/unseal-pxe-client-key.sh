#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
Unseal a TPM2 Client credential into volatile /run storage during trusted UKI boot.

Usage:
  FECLORA_ENCRYPTED_CREDENTIAL=/run/feclora/client-key.cred \
  FECLORA_CLIENT_KEY_OUTPUT=/run/feclora/client.key \
  bash build/unseal-pxe-client-key.sh

Requires the signed UKI PCR metadata exposed by systemd-stub at:
  /run/systemd/tpm2-pcr-signature.json
  /run/systemd/tpm2-pcr-public-key.pem

The output must remain under /run/feclora (tmpfs). No persistent fallback
or non-TPM decryption mode is permitted. This helper does not configure the
Client runtime or start a deployment job.
EOF
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || { usage; exit 0; }

INPUT="${FECLORA_ENCRYPTED_CREDENTIAL:-}"
OUTPUT="${FECLORA_CLIENT_KEY_OUTPUT:-}"
[[ -n "$INPUT" && -n "$OUTPUT" ]] || { usage >&2; exit 2; }
[[ -f "$INPUT" && ! -L "$INPUT" && -r "$INPUT" ]] || fail "Encrypted credential must be a readable regular non-symlink file."
[[ "$OUTPUT" == /run/feclora/* ]] || fail "Plaintext Client key must be written below /run/feclora."
[[ ! -L "$OUTPUT" && ! -e "$OUTPUT" ]] || fail "Plaintext output already exists or is a symlink."
CREDS="$(command -v systemd-creds || true)"
FINDMNT="$(command -v findmnt || true)"
[[ -n "$CREDS" && -n "$FINDMNT" ]] || fail "systemd-creds and findmnt are required."
[[ -s /run/systemd/tpm2-pcr-signature.json && -s /run/systemd/tpm2-pcr-public-key.pem ]] || fail "Trusted UKI PCR signature/public-key metadata is not present in /run/systemd."

[[ ! -L /run/feclora ]] || fail "/run/feclora must not be a symlink."
install -d -o root -g root -m 0700 /run/feclora
[[ "$(stat -c '%u:%g:%a' /run/feclora)" == "0:0:700" ]] || fail "/run/feclora must be owned by root with mode 0700."
[[ "$(readlink -f -- "$(dirname -- "$OUTPUT")")" == /run/feclora ]] || fail "Output parent must resolve exactly to /run/feclora."
[[ "$("$FINDMNT" -n -o FSTYPE -T /run/feclora)" == tmpfs ]] || fail "/run/feclora is not on tmpfs."
[[ "$(id -u)" -eq 0 ]] || fail "Credential unsealing must run as root."

TMP_DIR="$(mktemp -d /run/feclora/.unseal.XXXXXXXX)"
TMP="$TMP_DIR/client.key"
cleanup() { rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT

# systemd-creds consumes the PCR signature passed by systemd-stub and the
# TPM2 policy embedded in the encrypted credential. Any mismatch is fatal.
"$CREDS" --tpm2-device=auto decrypt "$INPUT" "$TMP"
[[ -s "$TMP" ]] || fail "TPM2 decryption produced an empty key."
chmod 0600 "$TMP"
ln -- "$TMP" "$OUTPUT"
rm -f -- "$TMP"
rmdir -- "$TMP_DIR"
trap - EXIT
printf 'Client private key unsealed into volatile root-only memory-backed storage.\n'
