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
  -nic user \
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
  -nic user \
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
- [ ] Cage/Firefox kiosk starts automatically on tty1; no desktop or console login prompt is presented.
- [ ] `/usr/share/feclora/python/feclora` contains the application payload.
- [ ] `/usr/share/cockpit/feclora/index.html` exists and is non-empty.
- [ ] `cockpit.socket` is enabled and active.
- [ ] The local first-boot assistant accepts a new administrator password and redirects to Cockpit.
- [ ] Cockpit presents no TLS warning; the localhost CA is trusted by Firefox.
- [ ] The `feclora` account was locked before setup and accepts the password created in the assistant.
- [ ] `cockpit.socket` listens only on `127.0.0.1:9090` and `[::1]:9090`.
- [ ] Certificate, bootstrap and kiosk systemd units reach the expected states.
- [ ] The Feclora Cockpit app opens and displays the Operations wizard.
- [ ] The legacy `dialog` package and `/usr/local/bin/feclora-ui` are absent from the supported Live image.
- [ ] Kernel command line and boot logs are captured.
- [ ] ISO checksum and VM firmware details are recorded.

## Cockpit login and screenshot capture

Use the VM's local display to complete the first-boot password assistant. It
binds only to guest loopback and is deliberately unavailable through QEMU
port forwarding. Firefox then opens Cockpit at `https://localhost:9090/cockpit/@localhost/feclora/index.html`.
Sign in as `feclora`, open the Feclora application and verify the Operations
workflow. The browser must not show a certificate interstitial; do not bypass
TLS validation. Cockpit listens on guest loopback only; no host port forwarding for 9090 is configured.

## Kiosk confinement and session behavior

- [ ] Firefox enterprise policy reports `WebsiteFilter` blocking all URLs except
  the local setup and Cockpit origins.
- [ ] Attempting an external URL is blocked; browser chrome and developer tools
  are unavailable in the kiosk session.
- [ ] systemd cgroup IP filters deny non-loopback destinations for Firefox and
  the bootstrap service while allowing Cockpit/setup loopback traffic.
- [ ] Killing Firefox or Cage causes the systemd kiosk service to restart it.
- [ ] getty@tty1–tty6 are masked and no autologin/passwordless-sudo setup exists.
- [ ] The `feclora-kiosk` account has no login shell and is not in `wheel`.
- [ ] The kiosk account cannot access privileged Cockpit/Feclora actions.
- [ ] Record keyboard/VT escape behavior on the actual target hardware.
- [ ] Reboot confirms current Live-session credentials and generated CA are
  ephemeral and the setup assistant appears again.

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
