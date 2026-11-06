# Virtual-machine smoke test

Run tests only against disposable virtual disks. Never use a host system disk as a test target.

## Boot
- [ ] ISO boots in BIOS mode.
- [ ] ISO boots in UEFI mode.
- [ ] Live session reaches a usable shell or supported UI.
- [ ] Kernel command line and boot logs are captured.

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

Record ISO checksum, Fedora release, kernel version, package manifest, VM firmware, and test results for every run.