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
- [ ] Firefox opens the Feclora Cockpit app directly on `http://127.0.0.1:9091/` with no login or password prompt.
- [ ] The interface-language selector is the first visible Feclora control and selecting a language updates the UI.
- [ ] The local kiosk service runs Cockpit in `--local-session` mode and is reachable only on `127.0.0.1:9091`.
- [ ] The ordinary authenticated `cockpit.socket` remains on `127.0.0.1:9090` and `[::1]:9090`.
- [ ] The `feclora` administrator account remains locked; no password is created.
- [ ] Certificate, local Cockpit kiosk and Firefox kiosk systemd units reach the expected states.
- [ ] The Feclora Cockpit app opens and displays the Operations wizard.
- [ ] The legacy `dialog` package and `/usr/local/bin/feclora-ui` are absent from the supported Live image.
- [ ] Kernel command line and boot logs are captured.
- [ ] ISO checksum and VM firmware details are recorded.

## Cockpit kiosk and screenshot capture

Use the VM's local display. Firefox must open the Feclora Cockpit app at
`http://127.0.0.1:9091/cockpit/@localhost/feclora/index.html` without asking
for a username or password. The interface-language selector must be the first
visible Feclora control; select a language and verify the Operations workflow.
The unauthenticated endpoint is bound to guest loopback only; do not forward
port 9091. The separate authenticated Cockpit socket remains on 9090 and is
also not forwarded.

## Kiosk confinement and session behavior

- [ ] Firefox enterprise policy reports `WebsiteFilter` blocking all URLs except
  the local Feclora Cockpit origin.
- [ ] Attempting an external URL is blocked; browser chrome and developer tools
  are unavailable in the kiosk session.
- [ ] systemd cgroup IP filters deny non-loopback destinations for Firefox and
  the local Cockpit kiosk endpoint while allowing loopback traffic.
- [ ] Killing Firefox or Cage causes the systemd kiosk service to restart it.
- [ ] getty@tty1–tty6 are masked and no autologin/passwordless-sudo setup exists.
- [ ] The `feclora-kiosk` account has no login shell and is not in `wheel`.
- [ ] The local Cockpit kiosk can perform the Feclora operations expected by the UI; the endpoint is only reachable from guest loopback.
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
