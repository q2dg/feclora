#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
Seal a Client TLS private key to that Client's TPM2 and signed UKI PCR policy.

Usage:
  FECLORA_TPM_PCR_PUBLIC_KEY=/path/to/feclora-pcr-public-key.pem \
  FECLORA_CLIENT_KEY=/etc/feclora/client.key \
  FECLORA_CREDENTIAL_OUTPUT=/root/feclora-client-key.cred \
  bash build/seal-pxe-client-key.sh

Run this on the enrolled Client itself. The private key is never uploaded:
only the resulting encrypted credential blob may be copied to the Server.
The credential is bound to TPM2 PCR 11 using the supplied UKI PCR signing
public key. No host-key, null-key or no-TPM fallback is permitted.
EOF
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || { usage; exit 0; }

PCR_KEY="${FECLORA_TPM_PCR_PUBLIC_KEY:-}"
CLIENT_KEY="${FECLORA_CLIENT_KEY:-}"
OUTPUT="${FECLORA_CREDENTIAL_OUTPUT:-}"
[[ -n "$PCR_KEY" && -n "$CLIENT_KEY" && -n "$OUTPUT" ]] || { usage >&2; exit 2; }
for input in "$PCR_KEY" "$CLIENT_KEY"; do
  [[ -f "$input" && ! -L "$input" && -r "$input" ]] || fail "Input must be a readable regular non-symlink file: $input"
done
[[ ! -L "$OUTPUT" && ! -e "$OUTPUT" ]] || fail "Credential output already exists or is a symlink."
OUT_DIR="$(dirname -- "$OUTPUT")"
[[ -d "$OUT_DIR" && ! -L "$OUT_DIR" ]] || fail "Credential output directory must already exist and must not be a symlink."
CREDS="$(command -v systemd-creds || true)"
[[ -n "$CREDS" ]] || fail "systemd-creds is required."

python3 - "$CLIENT_KEY" "$PCR_KEY" <<'PY'
import os, stat, sys
private_key, public_key = sys.argv[1:]
st = os.stat(private_key, follow_symlinks=False)
if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
    raise SystemExit("ERROR: Client private key must be a regular file with mode 0600 or stricter")
st = os.stat(public_key, follow_symlinks=False)
if not stat.S_ISREG(st.st_mode):
    raise SystemExit("ERROR: PCR public key must be a regular file")
PY

TMP_DIR="$(mktemp -d "$OUT_DIR/.feclora-credential.XXXXXXXX")"
TMP="$TMP_DIR/client-key.cred"
cleanup() { rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT

# Explicit tpm2 mode is essential. Do not replace it with systemd-creds'
# default auto mode: that could also bind to a persistent host credential key.
"$CREDS" --with-key=tpm2 --tpm2-device=auto \
  --tpm2-public-key="$PCR_KEY" --tpm2-public-key-pcrs=11 \
  encrypt "$CLIENT_KEY" "$TMP"
[[ -s "$TMP" ]] || fail "systemd-creds did not produce an encrypted credential."
chmod 0600 "$TMP"
ln -- "$TMP" "$OUTPUT"
rm -f -- "$TMP"
rmdir -- "$TMP_DIR"
trap - EXIT
printf 'TPM2-bound encrypted Client credential created: %s\n' "$OUTPUT"
printf 'Only ciphertext may be copied to the Server; keep the private key local.\n'
