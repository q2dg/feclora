---
layout: default
title: Build and validate the live ISO
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

# Build and validate the Live ISO

This runbook covers the Fedora 45 x86_64 Live appliance. GTK4/libadwaita is the production operator interface, launched by Weston DRM/KMS on tty1. Static checks and
unit tests do not establish that an ISO builds or boots; keep BIOS, UEFI and
physical-hardware acceptance results separate from automated test results.

## Build host

Use Fedora 45 x86_64 with working Fedora repositories, KVM access, QEMU,
Lorax, xorriso and enough free space for the installer ISO and build tree.
Install dependencies with:

```bash
make deps
```

Obtain the official Fedora 45 x86_64 DVD ISO and verify its SHA-256 against
Fedora's published checksum. Then set the input path:

```bash
export FEDORA_INSTALL_ISO="$PWD/Fedora-45-x86_64-DVD.iso"
test -f "$FEDORA_INSTALL_ISO"
```

The project intentionally does not switch Fedora baselines automatically.
Update and test the baseline before substituting a different release.

## Validate and build

Run the complete hardware-independent validation suite and build preflight:

```bash
make validate
make preflight FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
make build FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
```

`make validate` includes static project checks, documentation-link and guide
asset checks, Python compilation, GTK boot-configuration checks and the
hardware-independent unit tests. Use `make test` when you want to rerun only
the unit tests.

The build stages the Python application, adds it to a temporary installer ISO,
and runs `livemedia-creator` with QEMU virtualization. The resulting
`out/feclora-live.iso` is checked for BIOS and UEFI text-console arguments and
absence of Plymouth from the shipped boot initramfs. The Live image boots the unprivileged GTK interface on tty1 after visible
kernel/systemd messages. Weston DRM/KMS uses `kiosk-shell`; Cage is not used.
The Kickstart installs Fedora's official Weston, GTK4, libadwaita and PyGObject
RPMs and excludes the separate Xorg and XWayland server packages.

SELinux permissive mode remains the diagnostic default and adds `enforcing=0`
to the ISO boot arguments. Use `FECLORA_SELINUX_PERMISSIVE=0` to build an
enforcing image; permissive mode audits denials but does not enforce them.
Review AVC denials before selecting enforcing mode for release.

The temporary Anaconda installer VM is booted with `selinux=0` to avoid AVC
noise from its privileged `%post` scripts. This does not alter SELinux in the
generated Live image; the ISO verifier rejects `selinux=0` in its boot entries.

## BIOS and UEFI smoke test

With QEMU and OVMF installed, run:

```bash
python3 tests/vm/run-boot-smoke.py --iso out/feclora-live.iso
```

This headless test verifies that both firmware variants boot and GTK
renders its initial window, reported over a test-only virtio-serial channel.
It does **not** capture the terminal display or prove that a human can use
every workflow. Manually boot both firmware modes with a visible QEMU display
and verify boot messages, the tty1 handoff, keyboard navigation, VT switching
to tty2 and service recovery.

## Manual boot acceptance

- [ ] BIOS and UEFI select the first GRUB entry without a visible menu.
- [ ] System boot messages remain visible until GTK takes over tty1; no
      persistent black screen or boot splash appears.
- [ ] `feclora-gtk.service` runs Weston and GTK on tty1 as the locked, unprivileged
      `feclora` account.
- [ ] The GTK interface accepts keyboard input, including first-boot language and
      keyboard-layout selection.
- [ ] Tab, Shift+Tab, arrows, Enter and Space reach and activate each
      implemented control, including long and scrollable forms.
- [ ] The root terminal action opens the independent raw tty2 maintenance VT; exiting the shell returns to GTK on tty1. The tty2 root shell has no password prompt, so physical access must be restricted.
- [ ] Fedora 45 KMSCON instances are masked on tty1–tty6 so a userspace DRM console cannot retain the GPU while Feclora owns the VTs.
- [ ] The GTK interface reaches the fixed allowlisted helper through
      sudo; no general passwordless shell or unrestricted root command is
      available to `feclora`.
- [ ] Server/PXE preflight, local storage confirmation and error states are
      visible without relying on mouse input.
- [ ] A reboot recovers unfinished local operations as interrupted and starts
      GTK on tty1.
- [ ] Kernel command line, firmware details, ISO checksum and test results are
      recorded.

Only use disposable virtual disks for destructive-workflow acceptance.
Never attach a host system disk to a test VM.

GTK/Weston is the production boot route. Keep BIOS/UEFI,
physical-hardware and destructive-workflow acceptance results separate from
source-level checks; a successful GTK window alone does not validate every
workflow or every hardware configuration.
