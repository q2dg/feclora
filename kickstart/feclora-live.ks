#version=F45
# feclora initial rescue-live Kickstart for Fedora 45 x86_64.
# This recipe is a starting point and must pass build and boot tests.

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
@^minimal-environment
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

# Cockpit web interface; primary operator entry point
cockpit
cockpit-system
cockpit-storaged

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
age
minisign
nvme-cli
smartmontools
e2fsprogs
xfsprogs
btrfs-progs
dosfstools
ntfs-3g
pciutils
usbutils
lshw
%end

%post --erroronfail
systemctl --root=/ enable NetworkManager
systemctl --root=/ enable cockpit.socket

# Live rescue console: physical access to this image grants an automatic
# feclora shell and passwordless sudo. Do not reuse this policy on an installed OS.
useradd --create-home --groups wheel --shell /bin/bash feclora
passwd --delete feclora
cat > /home/feclora/.bash_profile <<'EOF'
# Cockpit is the primary operator interface. Set the live user's password
# from this console before signing in to Cockpit.
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] && [ -z "${FECLORA_WELCOME_SHOWN:-}" ]; then
  export FECLORA_WELCOME_SHOWN=1
  printf '\nFeclora Cockpit: https://<this-machine-ip>:9090\n'
  printf 'Set a login password with: sudo passwd feclora\n'
  printf 'Then open Cockpit from a trusted management network.\n\n'
fi
EOF
chown feclora:feclora /home/feclora/.bash_profile
chmod 0644 /home/feclora/.bash_profile
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin feclora --noclear %I $TERM
Type=idle
EOF
mkdir -p /etc/sudoers.d
echo '%wheel ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/feclora-wheel
chmod 0440 /etc/sudoers.d/feclora-wheel
restorecon -RF /home/feclora /etc/sudoers.d /etc/systemd/system/getty@tty1.service.d || true
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
  status|inventory|images|journals|operations|initialize_security|network_interfaces|bootstrap_server|deployment_jobs|create_deployment_job|reconcile_deployment_job|start_deployment_service|deployment_service_status|stop_deployment_service|arm_deployment_job|cancel_deployment_job|inspect_remote_job|inspect_client_csr|approve_client_csr|prepare_client_request|complete_client_enrollment|validate_pxe_profile|start_pxe_services|stop_pxe_services|pxe_service_status|capture_disk|capture_partition|restore_disk|restore_partition|clone_disk|clone_partition) ;;
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
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-deployment@.service" "$TARGET_ROOT/etc/systemd/system/feclora-deployment@.service"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-client@.service" "$TARGET_ROOT/etc/systemd/system/feclora-client@.service"
install -d -m 0700 "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora"
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora/images"
chown --reference="$TARGET_ROOT/home/feclora" "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
chown root:root "$TARGET_ROOT/var/lib/feclora/images"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/images"
%end

shutdown
