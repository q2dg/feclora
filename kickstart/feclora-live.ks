#version=F45
# Feclora Fedora Server minimal Live kiosk Kickstart for Fedora 45 x86_64.
# Live boot is retained; Firefox/Cage is the only local interactive shell.

text
cdrom
lang en_US.UTF-8
keyboard --xlayouts='us'
timezone Etc/UTC --utc
rootpw --lock
firewall --enabled
selinux --enforcing
bootloader --timeout=3
network --bootproto=dhcp --activate
zerombr
clearpart --all --initlabel
part / --fstype=ext4 --size=8192 --grow

%packages --excludedocs
@^server-product-environment
-@container-management
-@headless-management
kernel
tar
sudo
python3
kbd
psmisc
NetworkManager
iproute
firewalld
openssl
ca-certificates

# Cockpit web interface; primary operator entry point
cockpit
cockpit-system
cockpit-storaged

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
dracut-config-generic
dracut-network
dracut-live
grub2-efi-x64
grub2-pc-modules
shim-x64
syslinux

# Storage and inspection tools
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
nvme-cli
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

# The administrator account starts locked. The local first-boot
# assistant sets its password before Cockpit accepts the administrator login.
useradd --create-home --groups wheel --shell /bin/bash feclora
passwd --lock feclora

# Firefox runs as a separate unprivileged account, never as the administrator.
useradd --system --no-create-home --home-dir /var/lib/feclora-kiosk \
  --shell /sbin/nologin --user-group feclora-kiosk
install -d -o feclora-kiosk -g feclora-kiosk -m 0700 /var/lib/feclora-kiosk

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
cp -a "$APP_SOURCE/." "$TARGET_ROOT/usr/share/feclora/python/feclora/"
install -d "$TARGET_ROOT/usr/local/bin" "$TARGET_ROOT/usr/libexec/feclora" "$TARGET_ROOT/usr/share/cockpit/feclora"
cp -a "$WEB_SOURCE/." "$TARGET_ROOT/usr/share/cockpit/feclora/"
cat > "$TARGET_ROOT/usr/libexec/feclora/cockpit-api" <<'EOF'
#!/bin/sh
set -eu
case "${1:-}" in
  status|inventory|images|journals|operations|systemd_credentials|sftp_repositories|save_sftp_repository|remove_sftp_repository|inspect_sftp_image_set|list_sftp_image_manifests|fetch_sftp_image_set|publish_sftp_image_set|put_systemd_credential|remove_systemd_credential|remote_repositories|add_remote_repository|update_remote_repository|check_remote_repository|mount_remote_repository|unmount_remote_repository|remove_remote_repository|repository_images|initialize_security|network_interfaces|network_connection_profiles|apply_network_profile|bootstrap_server|deployment_jobs|create_deployment_job|reconcile_deployment_job|start_deployment_service|deployment_service_status|stop_deployment_service|arm_deployment_job|cancel_deployment_job|inspect_remote_job|start_client_job|client_job_status|validate_pxe_profile|start_pxe_services|stop_pxe_services|pxe_service_status|publish_pxe_answer|revoke_pxe_answer|provide_pxe_age_passphrase|pxe_age_passphrase_status|submit_local_operation|local_operation_status|local_operations|cancel_local_operation|capture_disk|capture_partition|restore_disk|restore_partition|clone_disk|clone_partition|extract_partition_image) ;;
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
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-restore-profile-env" "$TARGET_ROOT/usr/local/libexec/feclora-restore-profile-env"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-restore-profile.service" "$TARGET_ROOT/etc/systemd/system/feclora-restore-profile.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-pxe-answer.service" "$TARGET_ROOT/etc/systemd/system/feclora-pxe-answer.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-deployment@.service" "$TARGET_ROOT/etc/systemd/system/feclora-deployment@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-client@.service" "$TARGET_ROOT/etc/systemd/system/feclora-client@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-local-operation@.service" "$TARGET_ROOT/etc/systemd/system/feclora-local-operation@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-local-operation-recovery.service" "$TARGET_ROOT/etc/systemd/system/feclora-local-operation-recovery.service"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-cockpit-certificate" "$TARGET_ROOT/usr/libexec/feclora/feclora-cockpit-certificate"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-launch" "$TARGET_ROOT/usr/libexec/feclora/feclora-kiosk-launch"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-bootstrap-ready" "$TARGET_ROOT/usr/libexec/feclora/feclora-kiosk-bootstrap-ready"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-cockpit-certificate.service" "$TARGET_ROOT/etc/systemd/system/feclora-cockpit-certificate.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk-bootstrap.service" "$TARGET_ROOT/etc/systemd/system/feclora-kiosk-bootstrap.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-kiosk.service" "$TARGET_ROOT/etc/systemd/system/feclora-kiosk.service"
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
systemctl --root="$TARGET_ROOT" enable feclora-local-operation-recovery.service feclora-pxe-answer.service
systemctl --root="$TARGET_ROOT" enable feclora-cockpit-certificate.service feclora-kiosk-bootstrap.service feclora-kiosk.service
systemctl --root="$TARGET_ROOT" set-default graphical.target
systemctl --root="$TARGET_ROOT" mask getty@tty1.service getty@tty2.service getty@tty3.service getty@tty4.service getty@tty5.service getty@tty6.service
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora/images"
chown --reference="$TARGET_ROOT/home/feclora" "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
chown root:root "$TARGET_ROOT/var/lib/feclora/images"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/images"
%end

shutdown
