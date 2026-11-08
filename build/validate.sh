#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
errors=0
fail() { printf 'ERROR: %s\n' "$*" >&2; errors=$((errors + 1)); }

for file in "$ROOT_DIR/build/build-iso.sh" "$ROOT_DIR/build/preflight.sh" "$ROOT_DIR/build/install-host-deps.sh" "$ROOT_DIR/kickstart/feclora-live.ks" "$ROOT_DIR/packages/base.txt" "$ROOT_DIR/src/feclora/storage/inventory.py" "$ROOT_DIR/src/feclora/storage/volume_metadata.py" "$ROOT_DIR/tests/test_volume_metadata.py" "$ROOT_DIR/src/feclora/storage/volume_topology.py" "$ROOT_DIR/tests/test_volume_topology.py" "$ROOT_DIR/src/feclora/storage/btrfs_inventory.py" "$ROOT_DIR/tests/test_btrfs_inventory.py" "$ROOT_DIR/src/feclora/storage/stratis_inventory.py" "$ROOT_DIR/tests/test_stratis_inventory.py" "$ROOT_DIR/src/feclora/network/interface_discovery.py" "$ROOT_DIR/tests/test_interface_discovery.py" "$ROOT_DIR/src/feclora/network/pxe_config.py" "$ROOT_DIR/src/feclora/network/pxe_preflight.py" "$ROOT_DIR/tests/test_pxe_preflight.py" "$ROOT_DIR/src/feclora/network/boot_assets.py" "$ROOT_DIR/tests/test_boot_assets.py" "$ROOT_DIR/tests/test_pxe_config.py" "$ROOT_DIR/src/feclora/storage/restore_profile.py" "$ROOT_DIR/src/feclora/storage/profile_executor.py" "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" "$ROOT_DIR/src/feclora/data/feclora-restore-profile.service" "$ROOT_DIR/src/feclora/ui/dialog_app.py" "$ROOT_DIR/scripts/feclora-ui.sh"; do
  [[ -f "$file" ]] || fail "Required project file is missing: $file"
done

if [[ -f "$ROOT_DIR/README.md" ]]; then
  grep -q 'Fedora Linux 45' "$ROOT_DIR/README.md" || fail "README does not identify Fedora Linux 45 as the current project baseline."
  if grep -Eiq 'Fedora 43|F43|fc43|fedora-43' "$ROOT_DIR/README.md"; then
    fail "README still contains a stale Fedora 43 baseline reference."
  fi
fi

if [[ -f "$ROOT_DIR/kickstart/feclora-live.ks" ]]; then
  grep -q '^#version=F45$' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not declare Fedora 45 (#version=F45)."
  grep -q '^part / ' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not define a root partition."
  grep -qx 'dialog' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include dialog."
  grep -q '^%post --nochroot --erroronfail$' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not copy the app payload outside the chroot."
  grep -q 'APP_SOURCE=/run/install/repo/feclora-app/src/feclora' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart payload path does not match the mkksiso staging directory."
  grep -q 'usr/local/bin/feclora-ui' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the UI launcher."
  grep -q 'usr/local/bin/feclora-restore-profile' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the unattended restore profile launcher."
  grep -q 'feclora-restore-profile.service' "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not install the opt-in unattended restore service."
fi

if [[ -f "$ROOT_DIR/build/build-iso.sh" ]]; then
  grep -Fq "bash \"\${ROOT_DIR}/build/preflight.sh\"" "$ROOT_DIR/build/build-iso.sh" || fail "Build script must run host preflight before staging the ISO."
  grep -q -- '--make-iso' "$ROOT_DIR/build/build-iso.sh" || fail "Build script does not request ISO output."
  grep -Fq "mkksiso --add \"\${APP_STAGE}\" \"\${KS_FILE}\" \"\${INSTALL_ISO}\" \"\${AUGMENTED_ISO}\"" "$ROOT_DIR/build/build-iso.sh" || fail "mkksiso must receive the app payload, Kickstart, input ISO and output ISO in that order."
  if grep -Eq '^[[:space:]]+--no-virt([[:space:]]|$)' "$ROOT_DIR/build/build-iso.sh"; then
    fail "Unsafe --no-virt mode must not be enabled by the default build."
  fi
fi

if [[ -f "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" ]]; then
  bash -n "$ROOT_DIR/src/feclora/data/feclora-restore-profile-env" || fail "Unattended restore environment wrapper has invalid Bash syntax."
fi

if ! grep -qx 'dialog' "$ROOT_DIR/packages/base.txt"; then
  fail "Runtime package list does not include dialog."
fi

for package in dnsmasq ipxe-bootimgs-x86 caddy; do
  grep -qx "$package" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $package."
  grep -qx "$package" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $package."
done

for package in stratisd stratis-cli; do
  grep -qx "$package" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $package."
  grep -qx "$package" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $package."
done

for codec in zstd lz4; do
  grep -qx "$codec" "$ROOT_DIR/packages/base.txt" || fail "Runtime package list does not include $codec."
  grep -qx "$codec" "$ROOT_DIR/kickstart/feclora-live.ks" || fail "Kickstart does not include $codec."
done

while IFS= read -r -d '' script; do
  bash -n "$script" || fail "Bash syntax check failed: $script"
done < <(find "$ROOT_DIR/build" "$ROOT_DIR/scripts" -type f -name '*.sh' -print0 2>/dev/null || true)

if (( errors > 0 )); then
  printf 'Validation failed with %d error(s).\n' "$errors" >&2
  exit 1
fi
printf 'Static validation passed. This does not prove that the ISO builds or boots.\n'
