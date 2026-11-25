---
layout: default
title: Build and validate the live ISO
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

# Build and validate the Live ISO

This runbook covers the Fedora 45 x86_64 Live appliance; Textual remains the production boot UI while GTK/Weston parity is incomplete. Static checks and
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

Install the pinned UI-test dependency in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
```

Then run the complete hardware-independent validation suite and build
preflight:

```bash
make validate
make preflight FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
make build FEDORA_INSTALL_ISO="$FEDORA_INSTALL_ISO"
```

`make validate` includes static project checks, documentation-link and guide
asset checks, Python compilation, Textual boot-configuration checks and the
hardware-independent unit tests. Use `make test` when you want to rerun only
the unit tests.

The build stages the Python application, adds it to a temporary installer ISO,
and runs `livemedia-creator` with QEMU virtualization. The resulting
`out/feclora-live.iso` is checked for BIOS and UEFI text-console arguments and
absence of Plymouth from the shipped boot initramfs. The Live image currently boots the unprivileged Textual interface on tty1
after visible kernel/systemd messages. GTK4 is being migrated as the replacement
frontend. The target compositor is Weston DRM/KMS with `kiosk-shell`; Cage is
not used. Weston, GTK4 and libadwaita will only enter the image as Fedora-matched
X11-disabled builds after package inspection and behavioral parity. Textual
remains the production UI until the final Weston/GTK cutover.

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

This headless test verifies that both firmware variants boot and the GTK
welcome window is mapped inside Cage, reported over a test-only virtio-serial
channel. QEMU exposes a virtio display device for the guest DRM/KMS path. It does **not** capture the terminal display or prove that a human can
use every workflow. Manually boot both firmware modes with a visible QEMU
display and verify boot messages, the immediate Cage/GTK tty1 handoff,
keyboard navigation, VT switching to tty2 and service recovery.

## Manual boot acceptance

- [ ] BIOS and UEFI select the first GRUB entry without a visible menu.
- [ ] System boot messages remain visible until Textual takes over tty1; no
      persistent black screen or boot splash appears.
- [ ] `feclora-tui.service` runs Textual on tty1 as the locked, unprivileged
      `feclora` account while GTK/Weston parity is incomplete.
- [ ] The current Textual interface accepts keyboard input. The GTK welcome screen's
      language and keyboard-layout controls require separate acceptance.
- [ ] Tab, Shift+Tab, arrows, Enter and Space reach and activate each
      implemented control, including long and scrollable forms.
- [ ] The root terminal action opens tty2; exiting the shell returns to Textual on tty1.
- [ ] The GTK interface reaches the fixed allowlisted helper through sudo; no general
      passwordless shell or unrestricted root command is available to `feclora`.
- [ ] Server/PXE preflight, local storage confirmation and error states are
      visible without relying on mouse input.
- [ ] A reboot recovers unfinished local operations as interrupted and starts
      the GTK kiosk directly.
- [ ] Kernel command line, firmware details, ISO checksum and test results are
      recorded.

Only use disposable virtual disks for destructive-workflow acceptance.
Never attach a host system disk to a test VM.

The current boot route is an early switch to Cage/GTK requested before the
workflow migration and hardware acceptance are complete. The Textual unit
remains installed as a fallback. Treat the first BIOS/UEFI Cage startup, seat
acquisition, keyboard input, tty2 round-trip and physical display behavior as
unverified until the manual checklist is completed.

The Weston/GTK target is intentionally not enabled by the current Kickstart.
Before switching the boot unit, build Fedora 45-matched Weston and GTK4 RPMs
with their X11 backends disabled, rebuild libadwaita against that GTK, inspect
all package contents/dependencies, and complete the behavioral and firmware
acceptance gate documented in [GTK4-MIGRATION](GTK4-MIGRATION.md). The final
cutover removes Textual rather than retaining it as a fallback.
