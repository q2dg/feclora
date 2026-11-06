#version=F43
# Initial text-mode image recipe for Fedora 43 x86_64.
# This is a boot/build prototype, not yet an operator-ready live session.

text
cdrom
lang en_US.UTF-8
keyboard --xlayouts='us'
timezone Etc/UTC --utc
rootpw --lock
firewall --enabled
selinux --enforcing
bootloader --timeout=3
zerombr
clearpart --all --initlabel
part / --fstype=ext4 --size=8192 --grow

%packages --excludedocs
@^minimal-environment
kernel
dracut-live
NetworkManager
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
%end

reboot
