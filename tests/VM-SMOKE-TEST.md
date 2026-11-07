# Virtual-machine smoke test

Run tests only against disposable virtual disks. Never use a host system disk as a test target. The commands below boot the ISO without attaching any writable host block device.

## Preconditions

- Build completed and `out/feclora-live.iso` exists.
- QEMU is installed.
- For UEFI, install `edk2-ovmf` and locate the firmware with `rpm -ql edk2-ovmf | grep -E '/OVMF_CODE.*\.fd$'`.

## BIOS boot

On a graphical desktop:

```bash
qemu-system-x86_64 \
  -enable-kvm -m 4096 -smp 4 \
  -cdrom out/feclora-live.iso -boot order=d
```

If KVM is unavailable, remove `-enable-kvm` and expect slower execution.

## UEFI boot

Use the OVMF code firmware path installed on the host. For example, if the package provides `/usr/share/edk2/ovmf/OVMF_CODE.fd`:

```bash
qemu-system-x86_64 \
  -enable-kvm -m 4096 -smp 4 \
  -bios /usr/share/edk2/ovmf/OVMF_CODE.fd \
  -cdrom out/feclora-live.iso -boot order=d
```

Some OVMF setups require a writable variables image. If firmware initialization fails, create a per-test copy of the matching OVMF VARS file and attach it with `-drive if=pflash,format=raw,unit=1,file=...`; never modify the packaged firmware files.

## Boot acceptance

- [ ] ISO boots in BIOS mode.
- [ ] ISO boots in UEFI mode.
- [ ] Live session reaches the expected tty1 feclora shell.
- [ ] `sudo -n true` succeeds in this explicitly privileged rescue image.
- [ ] Kernel command line and boot logs are captured.
- [ ] ISO checksum and VM firmware details are recorded.

## Hardware discovery

- [ ] virtio block device is listed correctly.
- [ ] NVMe/SATA/USB discovery is tested where available.
- [ ] Device identity, capacity, and mount state are displayed accurately.

## Imaging safety

- [ ] Source and target are unambiguously identified.
- [ ] Destructive operations require explicit confirmation.
- [ ] Interrupted operations report failure and preserve useful logs.

## Image workflow

- [ ] Create a test image from a disposable disk.
- [ ] Verify image integrity.
- [ ] Restore to a second disposable disk.
- [ ] Compare partition layout and filesystem contents.

Record ISO checksum, Fedora release, kernel version, package manifest, VM firmware, and test results for every run. A boot test does not verify imaging functionality.
