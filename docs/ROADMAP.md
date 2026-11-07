# Roadmap

## Milestone 0 — Project foundation
- [x] Create the independent `feclora` repository.
- [x] Define Fedora 43 x86_64 as the initial target.
- [x] Publish an initial architecture decision record for the live-image build pipeline.
- [x] Confirm all GitHub Actions checks pass on the current main revision (verified on 2026-11-07; rerun after subsequent changes).
- [ ] Define the project license and contribution policy.

## Milestone 1 — Bootable live image
- [ ] Build a reproducible Fedora 43 live ISO.
- [ ] Boot on BIOS and UEFI in virtual machines.
- [ ] Provide a predictable live-session startup and logging.
- [x] Implement a read-only block-device/filesystem inventory with mocked unit tests.
- [x] Add an initial read-only device browser using the standard `dialog` utility.
- [x] Implement staging and Kickstart integration of feclora's Python code into the generated Live ISO (end-to-end ISO validation still pending).
- [x] Add automated build-host preflight checks for Fedora baseline, architecture, KVM, dependencies, inputs, and output space.
- [ ] Validate inventory and UI against real BIOS/UEFI virtual-machine storage.
- [x] Document the build-host preparation, ISO build, artifact checks, and VM acceptance procedure in [the build runbook](BUILD.md).

See [the Clonezilla Live functional-parity target](CLONEZILLA-FEATURE-PARITY.md) and [ADR 0003](adr/0003-clonezilla-workflow.md): use generic Linux utilities only; no Clonezilla or `ocs-*` runtime dependencies.

## Milestone 2 — Core imaging workflow
- [x] Discover the presence of standard storage utilities without executing them, including filesystem-specific Partclone executables.
- [x] Implement a tested, non-destructive whole-disk source/target selection gate.
- [x] Add an independent live-root dependency probe using `findmnt` and inverse `lsblk` metadata.
- [ ] Integrate root protection and selection into the TUI with a read-only plan preview.
- [ ] Validate root protection against Fedora Live BIOS/UEFI sessions, including overlay/loop-backed root layouts.
- [ ] Reproduce Clonezilla's `savedisk`/`saveparts`/`restoredisk`/`restoreparts` workflows using Partclone, sfdisk and dd; do not invent a new image engine.
- [ ] Reuse Clonezilla-compatible compression and checksum choices and image metadata.
- [ ] Record image metadata and operation logs.
- [ ] Port and test Clonezilla's busy-device, endpoint-identity and source/target checks before enabling writes.

## Milestone 3 — Compatibility expansion
- [ ] Add filesystem-aware and raw imaging modes.
- [ ] Add network image transports.
- [ ] Add encryption and advanced storage coverage where supported.
- [ ] Build a documented compatibility and regression test matrix.

## Milestone 4 — Network deployment
- [ ] Evaluate multicast and server-assisted deployment.
- [ ] Design PXE/UEFI network boot support as a separate subsystem.

Milestones are goals, not claims of existing functionality. Each item should be marked complete only after repeatable tests.
