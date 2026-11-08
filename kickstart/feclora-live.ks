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
dialog
kbd
psmisc
NetworkManager
iproute
firewalld
openssl

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

# Live rescue console: physical access to this image grants an automatic
# feclora shell and passwordless sudo. Do not reuse this policy on an installed OS.
useradd --create-home --groups wheel --shell /bin/bash feclora
passwd --delete feclora
cat > /home/feclora/.bash_profile <<'EOF'
# Launch the mode selector automatically on the primary live console.
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] && [ -z "${FECLORA_MENU_STARTED:-}" ]; then
  export FECLORA_MENU_STARTED=1
  exec /usr/local/bin/feclora-ui
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
TARGET_ROOT=/mnt/sysroot

if [ ! -d "$APP_SOURCE" ]; then
  echo "feclora application payload not found: $APP_SOURCE" >&2
  exit 1
fi

install -d "$TARGET_ROOT/usr/share/feclora/python/feclora"
cp -a "$APP_SOURCE/." "$TARGET_ROOT/usr/share/feclora/python/feclora/"
install -d "$TARGET_ROOT/usr/local/bin"
cat > "$TARGET_ROOT/usr/local/bin/feclora-ui" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/share/feclora/python${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m feclora.ui.mode_selector "$@"
EOF
chmod 0755 "$TARGET_ROOT/usr/local/bin/feclora-ui"
cat > "$TARGET_ROOT/usr/local/bin/feclora-restore-profile" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/share/feclora/python${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m feclora.storage.profile_executor "$@"
EOF
chmod 0755 "$TARGET_ROOT/usr/local/bin/feclora-restore-profile"
install -d "$TARGET_ROOT/usr/local/libexec" "$TARGET_ROOT/etc/systemd/system"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-restore-profile-env" "$TARGET_ROOT/usr/local/libexec/feclora-restore-profile-env"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-restore-profile.service" "$TARGET_ROOT/etc/systemd/system/feclora-restore-profile.service"
install -d -m 0700 "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
chown --reference="$TARGET_ROOT/home/feclora" "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
%end

shutdown
