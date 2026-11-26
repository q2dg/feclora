#version=F45
# Feclora Fedora 45 Live appliance Kickstart for x86_64.
# Use Fedora's core package group, not the full Server product environment.
# Textual remains the production tty1 UI until GTK/Weston parity and acceptance are complete.

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
python3-textual
weston
weston-libs
gtk4
libadwaita
python3-gobject
kbd
psmisc
NetworkManager
iproute
firewalld
openssl
ca-certificates

policycoreutils-python-utils
openssh-clients

# Embedded Server-mode PXE stack; services remain disabled until explicitly selected
# dnsmasq provides DHCP/ProxyDHCP, PXE and read-only TFTP; Caddy serves HTTP boot assets
dnsmasq
ipxe-bootimgs-x86
caddy
udpcast

# Required live-media boot components
curl
dracut-config-generic
dracut-network
dracut-live
grub2-efi-x64
grub2-efi-x64-cdboot
grub2-pc-modules
shim-x64
syslinux

# Exclude splash packages that may otherwise be selected by @core.
-plymouth
-plymouth-plugin-script
-plymouth-plugin-two-step
-plymouth-scripts

# Physical-to-virtual conversion and QCOW2 validation
qemu-img
xorriso

# Storage and inspection tools
python3-libguestfs
# Remote image repository mounts (enabled only by explicit operator action)
fuse-sshfs
nfs-utils
cifs-utils
age
partclone
ddrescue
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

# Keep the firewall enabled; no remote administration service is installed.
systemctl --root=/ enable firewalld.service

# Boot the default (first) GRUB entry immediately, without showing the menu.
cat >> /etc/default/grub <<'EOF'
GRUB_DEFAULT=0
GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_SAVEDEFAULT=false
EOF
grub2-mkconfig -o /boot/grub2/grub.cfg

# The local interface runs unprivileged; root actions are restricted to the API helper.
useradd --create-home --shell /sbin/nologin feclora
passwd --lock feclora

install -d -m 0750 /etc/sudoers.d
printf '%s\n' 'feclora ALL=(root) NOPASSWD: /usr/libexec/feclora/feclora-api *' \
  > /etc/sudoers.d/feclora-api
chmod 0440 /etc/sudoers.d/feclora-api
visudo -c -f /etc/sudoers.d/feclora-api

# Anaconda writes the installation disk UUID into fstab and kernel cmdline.
# Neither belongs in the generated LiveOS overlay: the ISO boots via root=live.
if [ -f /etc/fstab ]; then
  awk '/^[[:space:]]*#/ || NF == 0 { print; next } $2 != "/" { print }' /etc/fstab > /etc/fstab.feclora
  install -m 0644 /etc/fstab.feclora /etc/fstab
  rm -f /etc/fstab.feclora
fi
rm -f /etc/kernel/cmdline

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
install -d "$TARGET_ROOT/usr/local/bin" "$TARGET_ROOT/usr/libexec/feclora"
install -d "$TARGET_ROOT/usr/share/feclora"
install -d "$TARGET_ROOT/usr/lib/tmpfiles.d"
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-image-browser-cache.conf" "$TARGET_ROOT/usr/lib/tmpfiles.d/feclora-image-browser-cache.conf"
chroot "$TARGET_ROOT" /usr/sbin/restorecon -RF \
  /usr/share/feclora/python/feclora
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-api" "$TARGET_ROOT/usr/libexec/feclora/feclora-api"
chroot "$TARGET_ROOT" /usr/sbin/restorecon -F /usr/libexec/feclora/feclora-api
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
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui.service" "$TARGET_ROOT/etc/systemd/system/feclora-tui.service"
# Stage the GTK/Weston candidate without enabling it or changing the current boot route.
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk.service" "$TARGET_ROOT/etc/systemd/system/feclora-gtk.service"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-gtk-ready" "$TARGET_ROOT/usr/libexec/feclora/feclora-gtk-ready"
chroot "$TARGET_ROOT" /usr/sbin/restorecon -F /etc/systemd/system/feclora-gtk.service /usr/libexec/feclora/feclora-gtk-ready
install -m 0644 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-root-terminal.service" "$TARGET_ROOT/etc/systemd/system/feclora-root-terminal.service"
install -m 0755 "$TARGET_ROOT/usr/share/feclora/python/feclora/data/feclora-tui-ready" "$TARGET_ROOT/usr/libexec/feclora/feclora-tui-ready"
install -d -m 0700 "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora" "$TARGET_ROOT/var/lib/feclora/pxe" "$TARGET_ROOT/var/lib/feclora/client-jobs"
chown root:root "$TARGET_ROOT/var/lib/feclora/pxe"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/pxe"
chown root:root "$TARGET_ROOT/var/lib/feclora/client-jobs"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/client-jobs"
systemctl --root="$TARGET_ROOT" enable feclora-local-operation-recovery.service feclora-pxe-answer.service feclora-recovery-boot.service
systemctl --root="$TARGET_ROOT" enable feclora-tui.service
systemctl --root="$TARGET_ROOT" mask getty@tty1.service
systemctl --root="$TARGET_ROOT" mask kmsconvt@tty1.service kmsconvt@tty2.service kmsconvt@tty3.service kmsconvt@tty4.service kmsconvt@tty5.service kmsconvt@tty6.service
systemctl --root="$TARGET_ROOT" set-default multi-user.target
systemctl --root="$TARGET_ROOT" mask getty@tty3.service getty@tty4.service getty@tty5.service getty@tty6.service
install -d -m 0700 "$TARGET_ROOT/var/lib/feclora/images"
chown --reference="$TARGET_ROOT/home/feclora" "$TARGET_ROOT/home/feclora/profiles" "$TARGET_ROOT/home/feclora/logs"
chown root:root "$TARGET_ROOT/var/lib/feclora/images"
chmod 0700 "$TARGET_ROOT/var/lib/feclora/images"
%end

# Ensure neither @core nor a dependency reintroduces boot-splash packages.
%post --erroronfail
plymouth_packages="$(rpm -qa --qf '%{NAME}\n' | grep -E '^plymouth' || true)"
if [ -n "$plymouth_packages" ]; then
  echo "Unexpected boot-splash packages installed: $plymouth_packages" >&2
  exit 1
fi

shopt -s nullglob
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
  echo "No generated initramfs found while verifying text-mode boot." >&2
  exit 1
fi
for initrd in "${initrds[@]}"; do
  modules="$(lsinitrd -m "$initrd")"
  if grep -Eq '^[[:space:]]*plymouth[[:space:]]*$' <<<"$modules"; then
    echo "The Plymouth dracut module is present in initramfs $initrd." >&2
    exit 1
  fi
  listing="$(lsinitrd "$initrd")"
  if grep -Eiq '(^|/)plymouth([/.-]|$)' <<<"$listing"; then
    echo "Plymouth resources are present in initramfs $initrd." >&2
    exit 1
  fi
done
%end
shutdown
