#version=F45
# Feclora Fedora 45 Live kiosk Kickstart for x86_64.
# Use Fedora's core package group, not the full Server product environment.
# Live boot is retained; Firefox/Cage is the only local interactive shell.

url --url=https://download.fedoraproject.org/pub/fedora/linux/releases/45/Everything/x86_64/os/

# Anaconda downloads hundreds of RPMs from Fedora mirrors. Transient mirror
# failures must not abort the entire ISO build after exhausting a short retry
# window. This runs in the installer environment before Anaconda configures DNF.
%pre --erroronfail
install -d -m 0755 /etc/dnf
cat > /etc/dnf/dnf.conf <<'EOF'
[main]
retries=20
timeout=60
minrate=1
max_parallel_downloads=3
EOF
%end
# Keep installation on the release tree; the optional updates repo is deliberately
# omitted because Anaconda initializes every configured repo even when it is not
# used for package installation, making ISO builds depend on the updates mirror.
lang en_US.UTF-8
keyboard --xlayouts='us'
timezone Etc/UTC --utc
rootpw --lock
firewall --enabled
selinux --enforcing
bootloader --timeout=0
network --bootproto=dhcp --activate
zerombr
clearpart --all --initlabel
# Create firmware-specific boot partitions (BIOS biosboot or UEFI ESP).
reqpart
part / --fstype=ext4 --size=8192 --grow

%packages --excludedocs
@core
kernel
tar
sudo
python3
python3-boto3
kbd
psmisc
NetworkManager
iproute
firewalld
openssl
ca-certificates

# Temporary SSH access for VirtualBox diagnostics only; remove before release.
openssh-server

# Cockpit web interface; primary operator entry point
cockpit
cockpit-system
cockpit-storaged
cockpit-ws-selinux

# Minimal Wayland kiosk compositor and Firefox browser (no desktop environment)
cage
firefox

# Embedded Server-mode PXE stack; services remain disabled until explicitly selected
# dnsmasq provides DHCP/ProxyDHCP, PXE and read-only TFTP; Caddy serves HTTP boot assets
dnsmasq
ipxe-bootimgs-x86
caddy
udpcast

# Required live-media boot components
plymouth
plymouth-plugin-script
curl
plymouth-plugin-two-step
plymouth-scripts
librsvg2-tools
dracut-config-generic
dracut-network
dracut-live
grub2-efi-x64
grub2-efi-x64-cdboot
grub2-pc-modules
shim-x64
syslinux

# Physical-to-virtual conversion and QCOW2 validation
qemu-img
xorriso

# Storage and inspection tools
python3-libguestfs
# Remote image repository mounts (enabled only by explicit Cockpit action)
fuse-sshfs
nfs-utils
cifs-utils
age
partclone
zstd
lz4
parted
gdisk
util-linux
lvm2
stratisd
stratis-cli
cryptsetup
smartmontools
e2fsprogs
xfsprogs
btrfs-progs
dosfstools
exfatprogs
f2fs-tools
ntfs-3g
pciutils
usbutils
lshw
%end

%post --erroronfail
systemctl --root=/ enable NetworkManager
systemctl --root=/ enable cockpit.socket

# TEMPORARY DIAGNOSTIC ACCESS ONLY: remove this account and SSH configuration
# before producing any official Feclora ISO. Use only behind VirtualBox NAT.
groupadd --system feclora-logs
useradd --create-home --groups feclora-logs --shell /bin/bash pepe
printf '%s\n' 'pepe:1234' | chpasswd
install -d -m 0755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/10-feclora-diagnostic.conf <<'EOF'
PasswordAuthentication yes
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers pepe
EOF
systemctl --root=/ enable sshd.service
firewall-offline-cmd --add-service=ssh

# Boot the default (first) GRUB entry immediately, without showing the menu.
cat >> /etc/default/grub <<'EOF'
GRUB_DEFAULT=0
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_SAVEDEFAULT=false
EOF
grub2-mkconfig -o /boot/grub2/grub.cfg

# The administrator account remains locked in the passwordless local kiosk profile.
useradd --create-home --groups wheel --shell /bin/bash feclora
passwd --lock feclora

# Firefox runs as a separate unprivileged account, never as the administrator.
useradd --system --no-create-home --home-dir /var/lib/feclora-kiosk \
  --shell /sbin/nologin --user-group feclora-kiosk
install -d -o feclora-kiosk -g feclora-kiosk -m 0700 /var/lib/feclora-kiosk
usermod --append --groups feclora-logs feclora-kiosk
install -d -o feclora-kiosk -g feclora-logs -m 2750 /var/log/feclora-kiosk

%end

# Copy the application payload from the augmented installer DVD into the
# installed live filesystem. mkksiso adds this directory at the DVD root.
%post --nochroot --erroronfail
set -eu
APP_SOURCE=/run/install/repo/feclora-app/src/feclora
WEB_SOURCE=/run/install/repo/feclora-app/webui/dist
TARGET_ROOT=/mnt/sysroot

if [ ! -d "$APP_SOURCE" ]; then
  echo "feclora application payload not found: $APP_SOURCE" >&2
  exit 1
fi
if [ ! -s "$WEB_SOURCE/index.html" ] || [ ! -s "$WEB_SOURCE/manifest.json" ]; then
  echo "Feclora Cockpit frontend payload is missing or incomplete: $WEB_SOURCE" >&2
  exit 1
fi

install -d "$TARGET_ROOT/usr/share/feclora/python/feclora"
PLYMOUTH_SOURCE="$APP_SOURCE/data/plymouth"
PLYMOUTH_TARGET="$TARGET_ROOT/usr/share/plymouth/themes/feclora"
if [ ! -s "$PLYMOUTH_SOURCE/feclora.plymouth" ] || [ ! -s "$PLYMOUTH_SOURCE/feclora.script" ] || [ ! -s "$PLYMOUTH_SOURCE/feclora-logo-dark.svg" ]; then
  echo "Feclora Plymouth theme assets are missing: $PLYMOUTH_SOURCE" >&2
  exit 1
fi
install -d "$PLYMOUTH_TARGET"
install -m 0644 "$PLYMOUTH_SOURCE/feclora.plymouth" "$PLYMOUTH_TARGET/feclora.plymouth"
install -m 0644 "$PLYMOUTH_SOURCE/feclora.script" "$PLYMOUTH_TARGET/feclora.script"
install -m 0644 "$PLYMOUTH_SOURCE/feclora-logo-dark.svg" "$PLYMOUTH_TARGET/feclora-logo-dark.svg"
cp -a "$APP_SOURCE/." "$TARGET_ROOT/usr/share/feclora/python/feclora/"
install -d "$TARGET_ROOT/usr/local/bin" "$TARGET_ROOT/usr/libexec/feclora" "$TARGET_ROOT/usr/share/cockpit/feclora"
install -d "$TARGET_ROOT/usr/lib/tmpfiles.d"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-image-browser-cache.conf" "$TARGET_ROOT/usr/lib/tmpfiles.d/feclora-image-browser-cache.conf"
cp -a "$WEB_SOURCE/." "$TARGET_ROOT/usr/share/cockpit/feclora/"
cat > "$TARGET_ROOT/usr/libexec/feclora/cockpit-api" <<'EOF'
#!/bin/sh
set -eu
case "${1:-}" in
  open_root_terminal|status|restore_profiles|create_restore_profile|get_keyboard_layout|set_keyboard_layout|check_capture_filesystem|verify_image|inspect_image_layout|browse_image|export_server_age_recipients|refresh_client_age_recipients|renew_server_certificate|rotate_server_keypair|provide_capture_passphrase|restore_logical_volume|export_p2v_s3|inventory|images|journals|operations|systemd_credentials|put_systemd_credential|remove_systemd_credential|s3_repositories|add_s3_repository|update_s3_repository|check_s3_repository|remove_s3_repository|s3_repository_images|remote_repositories|add_remote_repository|update_remote_repository|check_remote_repository|mount_remote_repository|unmount_remote_repository|remove_remote_repository|repository_images|initialize_security|network_interfaces|network_connection_profiles|apply_network_profile|bootstrap_server|deployment_jobs|import_deployment_job|create_deployment_job|reconcile_deployment_job|start_deployment_service|deployment_service_status|stop_deployment_service|arm_deployment_job|cancel_deployment_job|inspect_remote_job|start_client_job|client_job_status|validate_pxe_profile|start_pxe_services|stop_pxe_services|pxe_service_status|publish_pxe_answer|revoke_pxe_answer|provide_pxe_age_passphrase|pxe_age_passphrase_status|submit_local_operation|local_operation_status|local_operations|cancel_local_operation|capture_disk|capture_partition|capture_logical_volume|capture_p2v|import_p2v|build_recovery_iso|build_deployment_bundle|restore_disk|restore_partition|restore_proportional_disk|execute_restore_profile|clone_disk|clone_partition|extract_partition_image) ;;
  *) echo '{"ok":false,"error":"unsupported action"}' >&2; exit 2 ;;
esac
export PYTHONPATH="/usr/share/feclora/python${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m feclora.webapi "$1"
EOF
chmod 0755 "$TARGET_ROOT/usr/libexec/feclora/cockpit-api"
cat > "$TARGET_ROOT/usr/local/bin/feclora-restore-profile" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/share/feclora/python${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m feclora.storage.profile_executor "$@"
EOF
chmod 0755 "$TARGET_ROOT/usr/local/bin/feclora-restore-profile"
install -d "$TARGET_ROOT/usr/local/libexec" "$TARGET_ROOT/etc/systemd/system"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-restore-profile.service" "$TARGET_ROOT/etc/systemd/system/feclora-restore-profile.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-pxe-answer.service" "$TARGET_ROOT/etc/systemd/system/feclora-pxe-answer.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-recovery-boot.service" "$TARGET_ROOT/etc/systemd/system/feclora-recovery-boot.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-deployment@.service" "$TARGET_ROOT/etc/systemd/system/feclora-deployment@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-client@.service" "$TARGET_ROOT/etc/systemd/system/feclora-client@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-local-operation@.service" "$TARGET_ROOT/etc/systemd/system/feclora-local-operation@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-local-operation-recovery.service" "$TARGET_ROOT/etc/systemd/system/feclora-local-operation-recovery.service"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-cockpit-certificate" "$TARGET_ROOT/usr/libexec/feclora/feclora-cockpit-certificate"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-launch" "$TARGET_ROOT/usr/libexec/feclora/feclora-kiosk-launch"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-show-network-address" "$TARGET_ROOT/usr/libexec/feclora/feclora-show-network-address"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-diagnostics" "$TARGET_ROOT/usr/libexec/feclora/feclora-kiosk-diagnostics"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-cockpit-certificate.service" "$TARGET_ROOT/etc/systemd/system/feclora-cockpit-certificate.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk.service" "$TARGET_ROOT/etc/systemd/system/feclora-kiosk.service"
install -d -m 0755 "$TARGET_ROOT/etc/pam.d"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk.pam" "$TARGET_ROOT/etc/pam.d/feclora-kiosk"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-cockpit-kiosk.service" "$TARGET_ROOT/etc/systemd/system/feclora-cockpit-kiosk.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-root-terminal.service" "$TARGET_ROOT/etc/systemd/system/feclora-root-terminal.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-return.service" "$TARGET_ROOT/etc/systemd/system/feclora-kiosk-return.service"
install -d -m 0755 "$TARGET_ROOT/etc/firefox/policies" "$TARGET_ROOT/etc/systemd/system/cockpit.socket.d"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-firefox-policies.json" "$TARGET_ROOT/etc/firefox/policies/policies.json"
cat > "$TARGET_ROOT/etc/systemd/system/cockpit.socket.d/feclora.conf" <<'EOF'
[Unit]
Requires=feclora-cockpit-certificate.service
After=feclora-cockpit-certificate.service

[Socket]
ListenStream=
ListenStream=127.0.0.1:9090
ListenStream=[::1]:9090
EOF
install -d -m 0700 "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora" "$TARGET_ROOT/var/lib/feclora/pxe"
chown root:root "$TARGET_ROOT/var/lib/feclora/pxe"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/pxe"
systemctl --root="$TARGET_ROOT" enable feclora-local-operation-recovery.service feclora-pxe-answer.service feclora-recovery-boot.service
systemctl --root="$TARGET_ROOT" enable feclora-cockpit-certificate.service feclora-cockpit-kiosk.service
# Diagnostic boot: keep Plymouth disabled, but start the kiosk so Cage/Firefox can be tested.
systemctl --root="$TARGET_ROOT" enable feclora-kiosk.service
systemctl --root="$TARGET_ROOT" unmask getty@tty1.service
systemctl --root="$TARGET_ROOT" set-default graphical.target
systemctl --root="$TARGET_ROOT" mask getty@tty2.service getty@tty3.service getty@tty4.service getty@tty5.service getty@tty6.service
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora/images"
chown --reference="$TARGET_ROOT/home/feclora" "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
chown root:root "$TARGET_ROOT/var/lib/feclora/images"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/images"
%end

# Diagnostic Plymouth theme: a single image downloaded at build time from
# Wikimedia Commons (CC0). Keep the original Feclora theme installed unchanged.
%post --erroronfail
PLYMOUTH_THEME_DIR=/usr/share/plymouth/themes/feclora
rsvg-convert --width=640 --output="$PLYMOUTH_THEME_DIR/feclora-logo.png" "$PLYMOUTH_THEME_DIR/feclora-logo-dark.svg"
test -s "$PLYMOUTH_THEME_DIR/feclora-logo.png"

TEST_THEME_DIR=/usr/share/plymouth/themes/feclora-test
install -d "$TEST_THEME_DIR"
curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 --max-time 60 \
  'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f9/Colordrawn_Sun.svg/250px-Colordrawn_Sun.svg.png' \
  --output "$TEST_THEME_DIR/test-image.png"
test -s "$TEST_THEME_DIR/test-image.png"
cat > "$TEST_THEME_DIR/feclora-test.plymouth" <<'EOF'
[Plymouth Theme]
Name=Feclora diagnostic image
Description=Minimal single-image Plymouth diagnostic theme
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/feclora-test
ScriptFile=feclora-test.script
EOF
cat > "$TEST_THEME_DIR/feclora-test.script" <<'EOF'
Window.SetBackgroundTopColor(0.035, 0.075, 0.13);
Window.SetBackgroundBottomColor(0.012, 0.027, 0.055);

test_image = Image("test-image.png");
test_sprite = Sprite(test_image);
test_sprite.SetPosition(
    Window.GetWidth() / 2 - test_image.GetWidth() / 2,
    Window.GetHeight() / 2 - test_image.GetHeight() / 2,
    10000
);
EOF
cat > "$TEST_THEME_DIR/IMAGE-SOURCE.txt" <<'EOF'
Image: Colordrawn Sun.svg (PNG thumbnail rendition)
Author: Anpang01
Source: https://commons.wikimedia.org/wiki/File:Colordrawn_Sun.svg
Original file: https://upload.wikimedia.org/wikipedia/commons/f/f9/Colordrawn_Sun.svg
License: CC0 1.0 Universal Public Domain Dedication
Downloaded at ISO build time from Wikimedia Commons.
EOF

install -d /etc/dracut.conf.d
cat > /etc/dracut.conf.d/feclora-plymouth.conf <<'EOF'
add_dracutmodules+=" plymouth "
install_items+=" /usr/share/plymouth/themes/feclora/feclora.plymouth /usr/share/plymouth/themes/feclora/feclora.script /usr/share/plymouth/themes/feclora/feclora-logo.png /usr/share/plymouth/themes/feclora-test/feclora-test.plymouth /usr/share/plymouth/themes/feclora-test/feclora-test.script /usr/share/plymouth/themes/feclora-test/test-image.png /usr/lib64/plymouth/script.so "
EOF
plymouth-set-default-theme feclora-test -R
test "$(plymouth-set-default-theme)" = feclora-test
grep -q '^Theme=feclora-test$' /etc/plymouth/plymouthd.conf
shopt -s nullglob

# Validate kernel initramfs images only. The rescue image is generated
# separately by dracut and is not required to use the Feclora splash theme.
initrds=()
for initrd in /boot/initramfs-*.img; do
  [[ -f "$initrd" ]] || continue
  case "$initrd" in
    */initramfs-0-rescue-*.img)
      echo "Skipping rescue initramfs: $initrd"
      continue
      ;;
  esac
  initrds+=("$initrd")
done

if [ "${#initrds[@]}" -eq 0 ]; then
  echo "No generated initramfs found after selecting the Feclora Plymouth theme." >&2
  exit 1
fi
for initrd in "${initrds[@]}"; do
  listing="$(lsinitrd "$initrd")"
  modules="$(lsinitrd -m "$initrd")"
  if ! grep -Eq '^plymouth$' <<<"$modules"; then
    echo "The Plymouth dracut module is missing from initramfs $initrd." >&2
    exit 1
  fi
  theme_config="$(lsinitrd -f /etc/plymouth/plymouthd.conf "$initrd")"
  if ! grep -Eq '^[[:space:]]*Theme=feclora-test$' <<<"$theme_config"; then
    echo "Initramfs $initrd does not select the diagnostic image Plymouth theme." >&2
    exit 1
  fi
  for asset in \
    usr/share/plymouth/themes/feclora/feclora.plymouth \
    usr/share/plymouth/themes/feclora/feclora.script \
    usr/share/plymouth/themes/feclora/feclora-logo.png \
    usr/share/plymouth/themes/feclora-test/feclora-test.plymouth \
    usr/share/plymouth/themes/feclora-test/feclora-test.script \
    usr/share/plymouth/themes/feclora-test/test-image.png \
    usr/lib64/plymouth/script.so; do
    if ! grep -Fq "$asset" <<<"$listing"; then
      echo "Plymouth asset $asset is missing from initramfs $initrd." >&2
      exit 1
    fi
  done
done
%end

shutdown
