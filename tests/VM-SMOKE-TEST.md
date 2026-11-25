# Virtual-machine smoke test

This procedure validates the generated image, not the build pipeline itself.
For host preparation, input ISO verification, build commands and artifact
inspection, see [the build runbook](../docs/BUILD.md).

Run tests only against disposable virtual disks. Never use a host system disk
as a test target.

## Automated BIOS/UEFI readiness test

Prerequisites: a built `out/feclora-live.iso`, QEMU, KVM (optional but
recommended), and OVMF for UEFI. Run:

```bash
python3 tests/vm/run-boot-smoke.py --iso out/feclora-live.iso
```

The headless test boots both firmware variants without attaching host disks or
networking. It waits for the GTK welcome window to map inside Cage before
reporting over a test-only virtio-serial channel. This does not prove that the
display is visible to an operator or that every screen is usable; those require
the visible manual checks below.

## Visible BIOS/UEFI boot acceptance

- [ ] BIOS and UEFI boot the first GRUB entry without a visible menu.
- [ ] White-on-black boot messages remain visible until the GTK/Cage kiosk
      starts on tty1; there is no splash or persistent black screen.
- [ ] `feclora-gtk.service` runs Cage and GTK as the locked, unprivileged
      `feclora` account on tty1; Textual remains a manual fallback.
- [ ] The fullscreen GTK welcome screen offers language and keyboard-layout selection.
- [ ] Every implemented workflow is reachable using the keyboard: Tab,
      Shift+Tab, arrows, Enter and Space; focus remains visible.
- [ ] Keyboard-layout selection changes the system keyboard layout without
      requiring a mouse or restarting GTK.
- [ ] The root-terminal action opens tty2; exiting the shell returns the
      display to tty1.
- [ ] The interface can call only the validated helper through its scoped
      sudo rule; no unrestricted passwordless shell is available.
- [ ] Storage inventory, confirmation prompts and operation failures remain
      readable and actionable in the GTK interface.
- [ ] The root filesystem and session credentials are ephemeral; no browser, Xorg/XWayland, desktop environment or display manager is installed;
      Cage is the only compositor.
- [ ] Kernel command line, firmware details, ISO checksum and test results are
      recorded.

## Imaging acceptance

Exercise destructive workflows only with disposable virtual disks. These
checks remain unvalidated until performed against the built image.

- [ ] Attach disposable source and target disks and verify inventory identity,
      capacity and mount state.
- [ ] Capture an image and verify its manifest and integrity metadata.
- [ ] Restore to a second disposable disk after checking its stable identity.
- [ ] Verify read-back behavior and inspect cancellation/failure handling.
- [ ] Record all target images or data as disposable before starting a write.

A boot test does not verify storage operations. Record the tested commit,
Fedora release, kernel version, ISO checksum, QEMU version, VM firmware and
results for every run.
