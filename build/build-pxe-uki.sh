#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
Build a signed Feclora PXE UKI from an existing Fedora Live kernel/initramfs.

Usage:
  FECLORA_UKI_CONFIG=/root/uki/feclora-uki.conf \
  FECLORA_UKI_CMDLINE=/root/uki/feclora.cmdline \
  FECLORA_UKI_KERNEL=/boot/vmlinuz-<version> \
  FECLORA_UKI_INITRD=/boot/initramfs-<version>.img \
  FECLORA_UKI_OUTPUT=/srv/feclora/boot/feclora-live.efi \
  ./build/build-pxe-uki.sh

The root-owned ukify config must define [UKI] SecureBootPrivateKey and
SecureBootCertificate, plus at least one [PCRSignature:*] section with
PCRPrivateKey, PCRPublicKey and Phases. All private keys and the config
must be inaccessible to group/other. The PCR policy is operator-owned and
must be validated against the actual firmware, Secure Boot trust database,
TPM and recovery process before deployment.

This script builds and verifies a UKI; it does not enroll firmware keys,
configure PCR policy, provision TPM credentials, publish PXE assets, or
change the existing PXE boot menu.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || { usage; exit 0; }

CONFIG="${FECLORA_UKI_CONFIG:-}"
CMDLINE="${FECLORA_UKI_CMDLINE:-}"
KERNEL="${FECLORA_UKI_KERNEL:-}"
INITRD="${FECLORA_UKI_INITRD:-}"
OUTPUT="${FECLORA_UKI_OUTPUT:-}"
[[ -n "$CONFIG" && -n "$CMDLINE" && -n "$KERNEL" && -n "$INITRD" && -n "$OUTPUT" ]] || { usage >&2; exit 2; }

for input in "$CONFIG" "$CMDLINE" "$KERNEL" "$INITRD"; do
  [[ -f "$input" && ! -L "$input" && -r "$input" ]] || fail "Input must be a readable regular non-symlink file: $input"
done
[[ -s "$KERNEL" && -s "$INITRD" && -s "$CMDLINE" ]] || fail "Kernel, initramfs and command line must be non-empty."
[[ ! -L "$OUTPUT" ]] || fail "Output path must not be a symlink."
OUT_DIR="$(dirname -- "$OUTPUT")"
[[ -d "$OUT_DIR" && ! -L "$OUT_DIR" ]] || fail "Output directory must already exist and must not be a symlink."
[[ ! -e "$OUTPUT" ]] || fail "Refusing to overwrite an existing UKI."

UKIFY="${FECLORA_UKIFY:-}"
if [[ -z "$UKIFY" ]]; then
  UKIFY="$(command -v ukify || true)"
  [[ -n "$UKIFY" ]] || [[ ! -x /usr/lib/systemd/ukify ]] || UKIFY=/usr/lib/systemd/ukify
fi
[[ -n "$UKIFY" && -x "$UKIFY" ]] || fail "systemd ukify is required."
SBVERIFY="$(command -v sbverify || true)"
[[ -n "$SBVERIFY" ]] || fail "sbverify (sbsigntools) is required."
MEASURE="$(command -v systemd-measure || true)"
[[ -n "$MEASURE" ]] || fail "systemd-measure is required for PCR policy signing."

# Validate configuration structure and private-file permissions without
# printing any key path or secret-bearing configuration content.
python3 - "$CONFIG" "$CMDLINE" <<'PY'
import configparser, os, stat, sys
config_path, cmdline_path = sys.argv[1:]
for path in (config_path, cmdline_path):
    st = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        raise SystemExit(f"ERROR: {path} must be a regular file with mode 0600 or stricter")
cfg = configparser.ConfigParser(interpolation=None, strict=True)
try:
    with open(config_path, encoding="utf-8") as stream:
        cfg.read_file(stream)
except (OSError, UnicodeError, configparser.Error) as exc:
    raise SystemExit(f"ERROR: invalid UKI config: {exc}")
if not cfg.has_section("UKI"):
    raise SystemExit("ERROR: UKI config requires a [UKI] section")
for key in ("SecureBootPrivateKey", "SecureBootCertificate"):
    if not cfg.get("UKI", key, fallback="").strip():
        raise SystemExit(f"ERROR: [UKI] requires {key}")
for key in ("SecureBootPrivateKey",):
    path = cfg.get("UKI", key).strip()
    st = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        raise SystemExit("ERROR: Secure Boot private key must be a regular file with mode 0600 or stricter")
cert = cfg.get("UKI", "SecureBootCertificate").strip()
st = os.stat(cert, follow_symlinks=False)
if not stat.S_ISREG(st.st_mode):
    raise SystemExit("ERROR: Secure Boot certificate must be a regular file")
pcr_sections = [section for section in cfg.sections() if section.startswith("PCRSignature:")]
if not pcr_sections:
    raise SystemExit("ERROR: at least one [PCRSignature:name] section is required")
for section in pcr_sections:
    for key in ("PCRPrivateKey", "PCRPublicKey", "Phases"):
        if not cfg.get(section, key, fallback="").strip():
            raise SystemExit(f"ERROR: {section} requires {key}")
    path = cfg.get(section, "PCRPrivateKey").strip()
    st = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        raise SystemExit("ERROR: PCR private key must be a regular file with mode 0600 or stricter")
    public_path = cfg.get(section, "PCRPublicKey").strip()
    public_st = os.stat(public_path, follow_symlinks=False)
    if not stat.S_ISREG(public_st.st_mode):
        raise SystemExit("ERROR: PCR public key must be a regular file")
with open(cmdline_path, encoding="utf-8") as stream:
    cmdline = stream.read().strip()
if not cmdline or "\n" in cmdline or "\r" in cmdline:
    raise SystemExit("ERROR: kernel command line must be one non-empty line")
lower = cmdline.lower()
for forbidden in ("password=", "passwd=", "token=", "private_key=", "credential="):
    if forbidden in lower:
        raise SystemExit("ERROR: kernel command line appears to contain a secret")
PY

TMP_DIR="$(mktemp -d "$OUT_DIR/.feclora-uki.XXXXXXXX")"
TMP="$TMP_DIR/feclora-live.efi"
cleanup() { rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT

"$UKIFY" --config="$CONFIG" build \
  --linux="$KERNEL" --initrd="$INITRD" --cmdline="@$CMDLINE" --output="$TMP"
[[ -s "$TMP" ]] || fail "ukify did not produce a non-empty UKI."
"$UKIFY" inspect --all "$TMP" > "$TMP_DIR/inspect.txt"
grep -Eiq 'pcrsig|PCR signature' "$TMP_DIR/inspect.txt" || fail "UKI is missing its embedded PCR signature section."
grep -Eiq 'pcrpkey|PCR public key' "$TMP_DIR/inspect.txt" || fail "UKI is missing its embedded PCR public-key section."
CERT="$(python3 - "$CONFIG" <<'PY'
import configparser, sys
c = configparser.ConfigParser(interpolation=None)
c.read(sys.argv[1], encoding="utf-8")
print(c.get("UKI", "SecureBootCertificate"))
PY
)"
"$SBVERIFY" --cert "$CERT" "$TMP" >/dev/null
chmod 0644 "$TMP"
mv -- "$TMP" "$OUTPUT"
rmdir -- "$TMP_DIR"
trap - EXIT
printf 'Signed UKI created and signature verified: %s\n' "$OUTPUT"
printf 'This does not prove firmware trust enrollment, PCR policy acceptance, or TPM unsealing.\n'
