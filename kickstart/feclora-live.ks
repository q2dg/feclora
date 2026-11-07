#version=F43
# feclora initial rescue-live Kickstart for Fedora 43 x86_64.
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
NetworkManager

# Required live-media boot components
dracut-config-generic
dracut-network
dracut-live
grub2-efi-x64
grub2-pc-modules
shim-x64
syslinux

# Storage and inspection tools
parted
util-linux
lvm2
cryptsetup
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
systemctl enable NetworkManager

# Live rescue console: physical access to this image grants an automatic
# feclora shell and passwordless sudo. Do not reuse this policy on an installed OS.
useradd --create-home --groups wheel --shell /bin/bash feclora
passwd --delete feclora
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

shutdown
