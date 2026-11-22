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

## Automated BIOS/UEFI boot readiness

After building the ISO, run the headless QEMU smoke test:

```bash
python3 tests/vm/run-boot-smoke.py --iso out/feclora-live.iso
```

It boots both BIOS and UEFI guests without attaching host disks or networking
and waits for the guest to confirm HTTP 200 from the Feclora page, a Wayland
socket, and a running Firefox process. The optional virtio-serial channel
carries status only and is absent on physical systems. This checks boot
readiness, not the rendered splash image; visually inspect both firmware modes
below.

## Boot acceptance

- [ ] ISO boots in BIOS mode; GRUB does not display its menu and automatically selects the first entry.
- [ ] ISO boots in UEFI mode; GRUB does not display its menu and automatically selects the first entry.
- [ ] Weston/Firefox kiosk starts automatically on tty1; no desktop or console login prompt is presented.
- [ ] Plymouth displays only the static centered Feclora logo, with no spinner or progress animation.
- [ ] The screen does not remain black while Cockpit starts.
- [ ] `/usr/share/feclora/python/feclora` contains the application payload.
- [ ] `/usr/share/cockpit/feclora/index.html` exists and is non-empty.
- [ ] `cockpit.socket` is masked and inactive.
- [ ] `feclora-cockpit-kiosk.service` owns `127.0.0.1:9090` using `--local-session`.
- [ ] Firefox opens the Feclora Cockpit app directly on `http://127.0.0.1:9090/cockpit/@localhost/feclora/index.html` with no login or password prompt.
- [ ] The Feclora Cockpit app page returns successfully and does not display Cockpit's “Not found” page.
- [ ] Firefox opens its first window directly on Feclora in fullscreen kiosk mode, with no visible tabs or browser chrome.
- [ ] Firefox uses a normal (non-private) session.
- [ ] The first Feclora screen offers interface-language and keyboard-layout selection, a keyboard apply action, and the root-terminal button.
- [ ] Continuing from initial setup opens the Feclora operations app.
- [ ] Complete initial setup and at least one operation using only the keyboard; Tab/Shift+Tab reach every control, Enter/Space activate actions, tab navigation works from the keyboard, and focus remains visible.
- [ ] The local kiosk service runs Cockpit in `--local-session` mode and is reachable only on `127.0.0.1:9090`.
- [ ] No separate authenticated Cockpit socket or second listener is active.
- [ ] The `feclora` administrator account exists with its password locked; the current diagnostic image includes the temporary `pepe` console account, which must be removed before a release image is published.
- [ ] Certificate, local Cockpit kiosk and Firefox kiosk systemd units reach the expected states.
- [ ] The Feclora Cockpit app opens and displays the Operations wizard.
- [ ] Kernel command line and boot logs are captured.
- [ ] ISO checksum and VM firmware details are recorded.

## Cockpit kiosk and screenshot capture

Use the VM's local display. Firefox must open the Feclora Cockpit app at
`http://127.0.0.1:9090/cockpit/@localhost/feclora/index.html` without asking
for a username or password. The first Feclora screen must be the interface-language selector; select a language, continue, and verify the Operations menu.
The unauthenticated endpoint is bound to guest loopback only; do not forward
port 9090. The standard Cockpit socket is masked; do not forward this port.

## Kiosk confinement and session behavior

- [ ] Firefox enterprise policy reports `WebsiteFilter` blocking all URLs except
  the local Feclora Cockpit origin.
- [ ] Attempting an external URL is blocked; browser chrome and developer tools
  are unavailable in the kiosk session.
- [ ] systemd cgroup IP filters deny non-loopback destinations for Firefox and
  the local Cockpit kiosk endpoint while allowing loopback traffic.
- [ ] Killing Firefox or Weston causes the systemd kiosk service to restart it.
- [ ] tty1 is reserved for the graphical kiosk (`getty@tty1` is unmasked but conflicts with the kiosk service); tty2 remains available for the diagnostic console; getty@tty3–tty6 are masked; no autologin or NOPASSWD sudo setup exists.
- [ ] The `feclora-kiosk` account has no login shell and is not in `wheel`.
- [ ] The local Cockpit kiosk can perform the Feclora operations expected by the UI; the endpoint is only reachable from guest loopback.
- [ ] Record keyboard/VT escape behavior on the actual target hardware.
- [ ] Reboot confirms the local no-login kiosk starts directly again and the generated CA is recreated.

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
