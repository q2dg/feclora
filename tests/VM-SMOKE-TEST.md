# Virtual-machine smoke test

This procedure validates the generated image, not the build pipeline itself.
For host preparation, input ISO verification, build commands, and artifact
inspection, see [the build runbook](../docs/BUILD.md).

Run tests only against disposable virtual disks. Never use a host system disk
as a test target. The commands below boot the ISO without attaching any
writable host block device.

## Preconditions

- Build completed and `out/feclora-live.iso` exists.
- QEMU is installed.
- KVM is available (otherwise remove `-enable-kvm` and expect slower execution).
- For UEFI, install `edk2-ovmf` and locate the matching CODE and VARS files:

```bash
rpm -ql edk2-ovmf | grep -E '/OVMF_(CODE|VARS).*\.fd$'
```

## BIOS boot

On a graphical desktop:

```bash
qemu-system-x86_64 \
  -enable-kvm -m 4096 -smp 4 \
  -nic user,hostfwd=tcp::9090-:9090 \
  -cdrom out/feclora-live.iso -boot order=d
```

## UEFI boot

Use a matching OVMF CODE and VARS pair from the installed package. Exact file
names can vary by firmware variant. For the common non-secure-boot pair:

```bash
OVMF_DIR=/usr/share/edk2/ovmf
cp "$OVMF_DIR/OVMF_VARS.fd" /tmp/feclora-OVMF_VARS.fd
qemu-system-x86_64 \
  -enable-kvm -m 4096 -smp 4 \
  -nic user,hostfwd=tcp::9090-:9090 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_DIR/OVMF_CODE.fd" \
  -drive if=pflash,format=raw,file=/tmp/feclora-OVMF_VARS.fd \
  -cdrom out/feclora-live.iso -boot order=d
```

If the installed files use different names or reside elsewhere, set
`OVMF_DIR` and the filenames to the matching pair reported by `rpm -ql`.
Never modify the packaged VARS image; make a fresh writable copy for each
independent test run. Remove the temporary copy after the test.

## Boot acceptance

- [ ] ISO boots in BIOS mode.
- [ ] ISO boots in UEFI mode.
- [ ] Live session reaches the expected tty1 feclora shell.
- [ ] `sudo -n true` succeeds in this explicitly privileged rescue image.
- [ ] `/usr/share/feclora/python/feclora` contains the application payload.
- [ ] `/usr/share/cockpit/feclora/index.html` exists and is non-empty.
- [ ] `cockpit.socket` is enabled and active.
- [ ] The live user can set a password with `sudo passwd feclora`.
- [ ] Cockpit is reachable from the host through the forwarded port and accepts the live-user login.
- [ ] The Feclora Cockpit app opens and displays the Operations wizard.
- [ ] The legacy `dialog` package and `/usr/local/bin/feclora-ui` are absent from the supported Live image.
- [ ] Kernel command line and boot logs are captured.
- [ ] ISO checksum and VM firmware details are recorded.

## Cockpit login and screenshot capture

After the Live VM reaches the console, set a temporary password for the live operator:

```bash
sudo passwd feclora
```

From the host, open `https://localhost:9090` and accept the expected self-signed
certificate warning for this disposable test environment. Sign in as `feclora`,
open the Feclora application and verify the Operations workflow. Do not expose
port 9090 beyond the host-only QEMU user network.

For visual documentation, capture the real browser screens from this VM and
follow the [Cockpit screenshot capture plan](../docs/assets/screenshots/README.md).
Record the ISO's source commit and Fedora release with each screenshot set; redact
VM-generated hostnames, addresses and device identifiers before committing.

## Hardware discovery

- [ ] Attach a disposable virtio block disk and verify it is listed correctly.
- [ ] NVMe/SATA/USB discovery is tested where available.
- [ ] Device identity, capacity, and mount state are displayed accurately.

## Imaging safety

These are destructive-workflow acceptance checks for the implemented imaging
paths. They remain unvalidated until run against disposable virtual disks.

- [ ] Source and target are unambiguously identified.
- [ ] Destructive operations require explicit confirmation.
- [ ] Interrupted operations report failure and preserve useful logs.

## Image workflow

Run these checks only against disposable virtual disks. Local whole-disk and
partition capture/restore are implemented, but must still pass runtime acceptance.

- [ ] Create a test image from a disposable disk.
- [ ] Verify image integrity.
- [ ] Restore to a second disposable disk.
- [ ] Compare partition layout and filesystem contents.

Record ISO checksum, Git commit, Fedora release, kernel version, package
manifest, QEMU version, VM firmware, and test results for every run. A boot
test does not verify imaging functionality.
