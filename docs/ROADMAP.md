# Roadmap

## Milestone 0 — Project foundation
- [x] Create the independent `feclora` repository.
- [x] Define Fedora 43 x86_64 as the initial target.
- [x] Publish an initial architecture decision record for the live-image build pipeline.
- [x] Add static validation and GitHub Actions checks (execution status pending).
- [ ] Define the project license and contribution policy.

## Milestone 1 — Bootable live image
- [ ] Build a reproducible Fedora 43 live ISO.
- [ ] Boot on BIOS and UEFI in virtual machines.
- [ ] Provide a predictable live-session startup and logging.
- [ ] Inventory block devices and filesystems safely.

## Milestone 2 — Core imaging workflow
- [ ] Create and restore partition or disk images.
- [ ] Support compression and integrity verification.
- [ ] Record image metadata and operation logs.
- [ ] Validate source/target selection and destructive-operation safeguards.

## Milestone 3 — Compatibility expansion
- [ ] Add filesystem-aware and raw imaging modes.
- [ ] Add network image transports.
- [ ] Add encryption and advanced storage coverage where supported.
- [ ] Build a documented compatibility and regression test matrix.

## Milestone 4 — Network deployment
- [ ] Evaluate multicast and server-assisted deployment.
- [ ] Design PXE/UEFI network boot support as a separate subsystem.

Milestones are goals, not claims of existing functionality. Each item should be marked complete only after repeatable tests.
