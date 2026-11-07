# ADR 0001: Initial live-image build pipeline

- Status: Accepted as the initial implementation direction
- Date: 2026-11-07
- Scope: Fedora 43 x86_64 rescue live ISO

## Context

feclora needs a reproducible Fedora-native image build. The first milestone is a bootable live ISO, not yet a full disk-imaging product. Builds must be isolated from the developer's workstation wherever practical.

## Decision

Use Fedora Kickstart with Lorax `livemedia-creator`, invoking its QEMU-backed virtualized build path. The initial build expects a Fedora 43 x86_64 DVD installation ISO as its package source.

The build script must not silently fall back to `--no-virt`. Build output and installer logs are retained under the configured result directory for diagnosis.

## Initial host requirements

- Fedora 43 x86_64 build host (preferably a disposable VM)
- Root privileges for the build
- Lorax, lorax-lmc-virt and QEMU
- Fedora 43 x86_64 DVD installation ISO
- At least 4 vCPUs, 8 GiB RAM and 30 GiB free disk as a practical starting point

These are initial operational estimates, not verified minimum requirements.

## Validation gates

1. Static checks pass for shell scripts and required inputs.
2. Lorax completes and produces the expected ISO.
3. ISO boots in a BIOS virtual machine.
4. ISO boots in a UEFI virtual machine.
5. Live session discovers disposable virtual block devices.
6. Only after these gates pass may the corresponding roadmap items be marked verified.

## Consequences and limitations

- A successful CI run checks repository hygiene; it does not build or boot the ISO.
- BIOS, UEFI, Secure Boot and physical hardware compatibility remain unverified until tested.
- Fedora 43 remains the agreed initial baseline. Its lifecycle must be reviewed before publishing production images.
- The Kickstart's automatic live-console login and passwordless sudo are acceptable only for explicitly labelled rescue media where physical boot access grants administrative control. This policy must not be reused for an installed system.
