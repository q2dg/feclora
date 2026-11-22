#!/usr/bin/env bash
set -Eeuo pipefail

ISO_FILE="${1:-}"
REPORT="${2:-}"
SELINUX_MODE="${3:-enforcing}"
if [[ -z "$ISO_FILE" || -z "$REPORT" || ! -s "$ISO_FILE" ]]; then
  echo "Usage: $0 /path/to/feclora-live.iso /path/to/report.txt [enforcing|permissive]" >&2
  exit 2
fi
if [[ "$SELINUX_MODE" != enforcing && "$SELINUX_MODE" != permissive ]]; then
  echo "SELinux mode must be enforcing or permissive." >&2
  exit 2
fi

for command in xorriso lsinitrd; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required ISO verification command is missing: $command" >&2
    exit 127
  }
done

WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "$WORK_DIR"' EXIT
: > "$REPORT"

report() {
  printf '%s\n' "$*" | tee -a "$REPORT"
}

fail() {
  printf 'ERROR: %s\n' "$*" | tee -a "$REPORT" >&2
  exit 1
}

check_grub_config() {
  local firmware="$1" iso_path="$2" extracted="$WORK_DIR/grub-${1}.cfg" lines line
  if ! xorriso -osirrox on -indev "$ISO_FILE" -extract "$iso_path" "$extracted" >/dev/null 2>&1 \
    || [[ ! -s "$extracted" ]]; then
    fail "$firmware GRUB configuration is missing from the ISO: $iso_path"
  fi

  mapfile -t lines < <(grep -E '^[[:space:]]*linux(efi|16)?[[:space:]]' "$extracted" || true)
  (( ${#lines[@]} > 0 )) || fail "$firmware GRUB configuration has no Linux boot entries: $iso_path"
  report "--- $firmware kernel command lines ($iso_path) ---"
  for line in "${lines[@]}"; do
    report "$line"
    grep -Eq '(^|[[:space:]])rhgb([[:space:]]|$)' <<<"$line" \
      || fail "$firmware kernel entry does not enable the graphical Plymouth splash."
    if grep -Eq '(^|[[:space:]])rd\.plymouth=0([[:space:]]|$)' <<<"$line"; then
      fail "$firmware kernel entry disables Plymouth."
    fi
    if grep -Eq '(^|[[:space:]])selinux=0([[:space:]]|$)' <<<"$line"; then
      fail "$firmware kernel entry disables SELinux completely."
    fi
    if [[ "$SELINUX_MODE" == permissive ]]; then
      grep -Eq '(^|[[:space:]])enforcing=0([[:space:]]|$)' <<<"$line" \
        || fail "$firmware kernel entry does not enable diagnostic SELinux permissive mode."
    elif grep -Eq '(^|[[:space:]])enforcing=0([[:space:]]|$)' <<<"$line"; then
      fail "$firmware kernel entry enables diagnostic SELinux permissive mode in an enforcing build."
    fi
  done
}

report "ISO: $ISO_FILE"
report "Expected SELinux mode: $SELINUX_MODE"
check_grub_config BIOS /boot/grub2/grub.cfg
uefi_config=""
for candidate in /EFI/BOOT/grub.cfg /EFI/fedora/grub.cfg; do
  uefi_tmp="$WORK_DIR/grub-uefi-${RANDOM}.cfg"
  if xorriso -osirrox on -indev "$ISO_FILE" -extract "$candidate" "$uefi_tmp" >/dev/null 2>&1 \
    && [[ -s "$uefi_tmp" ]]; then
    mv "$uefi_tmp" "$WORK_DIR/grub-uefi.cfg"
    uefi_config="$candidate"
    break
  fi
  rm -f "$uefi_tmp"
done
[[ -n "$uefi_config" ]] || fail "UEFI GRUB configuration is missing from the ISO."
check_grub_config UEFI "$uefi_config"

INITRD="$WORK_DIR/iso-boot-initrd.img"
xorriso -osirrox on -indev "$ISO_FILE" -extract /images/pxeboot/initrd.img "$INITRD" >/dev/null 2>&1 \
  || fail "Could not extract /images/pxeboot/initrd.img from the ISO."
[[ -s "$INITRD" ]] || fail "The ISO boot initramfs is empty."

modules="$(lsinitrd -m "$INITRD")" || fail "Could not inspect the ISO boot initramfs modules."
grep -Fxq plymouth <<<"$modules" || fail "The ISO boot initramfs is missing the Plymouth dracut module."
theme_config="$(lsinitrd -f /etc/plymouth/plymouthd.conf "$INITRD")" \
  || fail "Could not read Plymouth configuration from the ISO boot initramfs."
grep -Eq '^[[:space:]]*Theme=feclora$' <<<"$theme_config" \
  || fail "The ISO boot initramfs does not select the Feclora Plymouth theme."

listing="$(lsinitrd "$INITRD")" || fail "Could not list the ISO boot initramfs contents."
for asset in \
  usr/share/plymouth/themes/feclora/feclora.plymouth \
  usr/share/plymouth/themes/feclora/feclora.script \
  usr/share/plymouth/themes/feclora/feclora-logo.png \
  usr/lib64/plymouth/script.so; do
  grep -Fq "$asset" <<<"$listing" || fail "The ISO boot initramfs is missing Plymouth asset: $asset"
done

report "--- Plymouth initramfs verification ---"
report "Dracut module: plymouth"
report "$theme_config"
report "Feclora theme, script, logo and script renderer are present."
report "ISO boot visual artifacts verified."
