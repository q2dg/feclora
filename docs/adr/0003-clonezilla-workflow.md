# ADR 0003: Generic storage tools and Clonezilla feature parity

- Status: Accepted
- Date: 2026-11-07
- Scope: Fedora Live ISO functionality

## Context

feclora is an independent Fedora-based rescue environment. Its product goal is
to provide the practical disk-imaging, restoration, cloning, and deployment
capabilities users expect from Clonezilla Live.

The implementation must use generic, independently maintained Linux tools.
Clonezilla-specific orchestration commands and scripts (including every
`ocs-*` program), DRBL, and Clonezilla Live components are explicitly out of
scope. Clonezilla is the functional reference, not a software dependency.

## Decision

Use standard utilities as the implementation primitives:

- `lsblk`, `blkid`, `findmnt`, `udevadm`: device and filesystem discovery.
- `partclone.*`: filesystem-aware used-block imaging where supported.
- `dd`: raw block copying, direct disk-to-disk cloning, and boot-area data when required.
- `sfdisk`, `sgdisk`, `parted`: partition-table backup, restore, and editing.
- `gzip`, `zstd`, `xz`, `pigz`: image compression, subject to availability.
- `sha256sum` and related standard tools: integrity verification.
- `lvm2`, `cryptsetup`, filesystem utilities: supported storage stacks.
- `openssh`, `netcat`/equivalent, and standard network tools: remote image
  transport; multicast tooling will be selected when that milestone is designed.

Feclora-specific code is limited to the user interface, orchestration of these
generic commands, device selection and safety validation, progress reporting,
logging, image metadata, and Fedora Live integration.

The feature target is functional parity, not command-line or image-format
compatibility at any cost. Where Clonezilla uses a proprietary-to-Clonezilla
container convention around generic image data, feclora will implement only
what is necessary to provide equivalent user-facing behavior using documented
formats and generic tools.

## Non-goals

- Do not invoke, package, port, or depend on `ocs-sr`, `ocs-onthefly`,
  `ocs-live`, other `ocs-*` scripts, or DRBL.
- Do not build a new filesystem imaging engine when Partclone or raw copying
  already provides the required primitive.
- Do not build replacement partitioning, compression, encryption, or checksum
  utilities.
- Do not enable destructive operations until source/target validation,
  revalidation, confirmation, and recovery/error handling are implemented.

## Consequences

- Clonezilla's user-visible feature set is the acceptance target.
- Each feature must be mapped to generic Fedora-packaged tools and tested in
  the Live ISO; feature parity is not inferred from package presence.
- The current application remains read-only. This ADR does not claim that
  imaging or restoration is implemented.
