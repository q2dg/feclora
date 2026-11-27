---
layout: default
title: Build and validate the live ISO
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

# Build and validate the Live ISO

This runbook covers the Fedora 45 x86_64 Live appliance. **Textual remains the
production operator interface on tty1.** GTK4/libadwaita on Weston is a staged
candidate only. Do not enable it or remove Textual until the strict X11-free
RPM build, semantic parity, automated tests and BIOS/UEFI acceptance gates in
[GTK4-MIGRATION.md](GTK4-MIGRATION.md) are complete.

Static checks and unit tests do not establish that an ISO builds or boots.
Keep BIOS, UEFI and physical-hardware acceptance results separate from
automated test results.

## Build host

Use Fedora 45 x86_64 with working Fedora repositories, KVM access, QEMU,
Lorax, xorriso and enough free space for the installer ISO and build tree.
Install dependencies with:

```bash
make deps
```

Create a test environment for the pinned Textual UI dependency:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
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

`make validate` checks that Textual remains installed and enabled on tty1,
tty2 remains a separate maintenance shell, the GTK candidate is not enabled,
the candidate requires native Wayland, Python sources compile and the
hardware-independent unit tests pass. It also runs the strict RPM verifier's
test suite. It does not build or certify the custom graphical RPMs.

The ISO build stages the Python application, adds it to a temporary installer
ISO, and runs `livemedia-creator` with QEMU virtualization. The resulting
`out/feclora-live.iso` is checked for BIOS and UEFI console arguments and
absence of Plymouth from the shipped boot initramfs. The Live image starts the
unprivileged Textual interface on tty1 after visible kernel/systemd messages.
The independent root maintenance terminal remains on tty2. KMSCON is masked
on tty1–tty6 so it cannot retain DRM while the appliance owns those VTs.

The Kickstart must not install stock Fedora `weston`, `weston-libs`,
`gtk4` or `libadwaita` RPMs. Those packages contain X11 modules or
dependencies and are prohibited by the strict appliance policy until rebuilt
from Fedora 45 sources and admitted by
`build/verify-wayland-rpms.sh`. `python3-gobject` remains a Fedora system
package; no GTK bindings are installed through pip.

SELinux permissive mode remains the diagnostic default and adds
`enforcing=0` to the ISO boot arguments. Use
`FECLORA_SELINUX_PERMISSIVE=0` to build an enforcing image; permissive mode
audits denials but does not enforce them. Review AVC denials before selecting
enforcing mode for release.

The temporary Anaconda installer VM is booted with `selinux=0` to avoid AVC
noise from its privileged `%post` scripts. This does not alter SELinux in the
generated Live image; the ISO verifier rejects `selinux=0` in its boot
entries.

## BIOS and UEFI smoke test

With QEMU and OVMF installed, run:

```bash
python3 tests/vm/run-boot-smoke.py --iso out/feclora-live.iso
```

This headless test verifies that both firmware variants boot and Textual
reports its first rendered screen over a test-only virtio-serial channel. It
does **not** capture the terminal display or prove that a human can use every
workflow. Manually boot both firmware modes with a visible QEMU display and
verify boot messages, the tty1 handoff, keyboard navigation, VT switching to
tty2 and service recovery.

## Manual boot acceptance

- [ ] BIOS and UEFI select the first GRUB entry without a visible menu.
- [ ] System boot messages remain visible until Textual takes over tty1; no
      persistent black screen or boot splash appears.
- [ ] `feclora-tui.service` runs Textual on tty1 as the locked, unprivileged
      `feclora` account.
- [ ] The first-boot language and keyboard-layout selectors work.
- [ ] Tab, Shift+Tab, arrows, Enter and Space reach and activate the operator
      controls, including long and scrollable forms.
- [ ] The root terminal action opens the independent raw tty2 maintenance VT;
      exiting the shell returns to the interface on tty1. The tty2 root shell
      has no password prompt, so physical access must be restricted.
- [ ] Fedora 45 KMSCON instances are masked on tty1–tty6.
- [ ] The UI reaches the fixed allowlisted helper through sudo; no general
      passwordless shell or unrestricted root command is available to
      `feclora`.
- [ ] Server/PXE preflight, local storage confirmation and error states are
      visible without relying on mouse input.
- [ ] A reboot recovers unfinished local operations as interrupted and starts
      Textual on tty1.
- [ ] Kernel command line, firmware details, ISO checksum and test results are
      recorded.

Only use disposable virtual disks for destructive-workflow acceptance.
Never attach a host system disk to a test VM.

Passing a Textual boot smoke test is not GTK acceptance. GTK activation remains
blocked on the separate source rebuild, strict RPM audit, semantic workflow
parity, Weston/logind/libseat session validation and BIOS/UEFI acceptance.
