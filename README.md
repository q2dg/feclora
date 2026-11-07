# feclora

**feclora** is an independent project to build a Fedora-based live system for disk imaging, cloning, and recovery, aiming for functional coverage comparable to Clonezilla.

It is not a fork of Clonezilla and does not depend on its repository, branches, or release process. Clonezilla may be used as a functional reference during requirements analysis; implementation and project history live here.

## Initial target

- Fedora 43
- x86_64
- Rescue-style bootable live ISO
- BIOS and UEFI boot support
- Native Fedora package management and system integration
- Imaging, cloning, restoration, and storage administration

The first milestone is a reproducible bootable live ISO with a verified core workflow. Broader functionality will be added in measured, testable increments.

## Design principles

1. **Independent implementation:** no upstream submodule, tracking branch, or automatic code synchronization.
2. **Fedora-native build:** use Fedora tooling and RPM packages; the initial image pipeline uses Lorax `livemedia-creator`, Kickstart, and QEMU.
3. **Modular capabilities:** keep image orchestration, storage discovery, filesystem support, networking, boot integration, and user interfaces separable.
4. **Safe operations:** make destructive actions explicit, validate source and target devices, and provide dry-run or confirmation paths where feasible.
5. **Reproducibility:** pin build inputs where practical and record package versions and build metadata.
6. **Tested compatibility:** document filesystem, partition-table, encryption, transport, firmware, and hardware coverage rather than assuming parity.

## Build and test

See [docs/BUILD.md](docs/BUILD.md) for the Fedora build-host prerequisites, installer ISO verification, build commands, output inspection, and BIOS/UEFI QEMU acceptance procedure. The focused [VM smoke-test checklist](tests/VM-SMOKE-TEST.md) records the boot and device-discovery checks.

## Repository layout

- `build/` — ISO build tooling and build-host setup
- `kickstart/` — Fedora installation and live-image configuration
- `packages/` — RPM package manifests
- `src/` — application and orchestration code
- `scripts/` — developer and operator utilities
- `tests/` — unit, integration, and VM smoke tests
- `docs/` — architecture, compatibility, and operational documentation

## Development status

Early implementation. The repository contains an initial Kickstart and a QEMU-backed `livemedia-creator` build script. The Python application payload is wired into the installer/Live image pipeline, but neither the ISO build nor BIOS/UEFI boot has yet been validated end to end. No functional parity claim is made yet.

## Fedora baseline lifecycle

Fedora 43 remains the agreed initial baseline, but its support window is close to ending. Keep the release version configurable and plan a tested migration to a currently supported Fedora release before publishing production images.

## License

License selection is pending. Individual components and dependencies may carry their own licenses; these will be documented before code is incorporated or redistributed.
