# ADR 0003: Follow Clonezilla's imaging workflow

- Status: Accepted
- Date: 2026-11-07
- Scope: disk/partition imaging and local disk-to-disk cloning

## Context

feclora is an independent Fedora-based rescue environment. Reimplementing
filesystem imaging, partition-table serialization, raw copying, compression,
and device eligibility rules would duplicate mature behavior already exercised
by Clonezilla.

Clonezilla's upstream scripts establish the relevant workflow:

- `ocs-onthefly` obtains hard-disk candidates, asks for source and destination,
  validates both selections, rejects identical endpoints, and checks whether
  devices are busy before processing.
- `ocs-sr` provides the established `savedisk`, `saveparts`,
  `restoredisk`, and `restoreparts` workflows.
- Partclone's filesystem-specific programs perform used-block imaging for
  supported filesystems; raw copying is the fallback for unsupported layouts.
- `sfdisk` handles partition-table capture/creation and `dd` handles raw
  sectors and boot-area data where Clonezilla's workflow requires it.
- Clonezilla's on-the-fly disk clone is orchestrated by `ocs-onthefly` and
  delegates image save/restore work to `ocs-sr`; it is not a home-grown
  filesystem-copy algorithm.

Primary upstream references:
- https://github.com/stevenshiau/clonezilla/blob/master/sbin/ocs-onthefly
- https://github.com/stevenshiau/clonezilla/blob/master/sbin/ocs-sr
- https://clonezilla.org/downloads/src/
- https://clonezilla.org/fine-print-live-doc.php?path=clonezilla-live%2Fdoc%2F98_ocs_related_command_manpages

## Decision

1. Reuse Fedora-packaged storage utilities wherever possible. Partclone is
   available in Fedora 43 and is added to the live-image package set.
2. Detect Partclone's filesystem-specific executables (for example,
   `partclone.ext4`, `partclone.ntfs`, `partclone.xfs` and
   `partclone.btrfs`), not a fictional generic `partclone` command.
3. Use `sfdisk` for partition-table workflows and `dd` for raw data only
   where the Clonezilla workflow calls for it.
4. Keep feclora-specific code limited to Fedora live boot integration, UI,
   invocation, progress/log presentation, and explicit safety gates.
5. Do not write a new filesystem imaging engine, partition-table format,
   compression implementation, or checksum algorithm.
6. Before incorporating upstream Clonezilla scripts or helper libraries,
   review their GPL licensing, dependencies on DRBL/Clonezilla Live, and
   compatibility with Fedora. The repository's own license must be decided
   before copying or adapting upstream source code.
7. Port Clonezilla's device eligibility and endpoint checks deliberately.
   Do not treat a simple mountpoint scan as equivalent to Clonezilla's
   `get_not_busy_disks_or_parts`, `check_input_hd`,
   `check_if_input_device_exist`, and `check_if_dev_busy` logic.

## Consequences

- The current capability detector reports the actual per-filesystem Partclone
  executables.
- The current TUI and selection code remain read-only; this ADR does not enable
  imaging or disk writes.
- Clonezilla's orchestration scripts are not assumed to run unmodified on
  Fedora. Their DRBL environment and dependencies must be evaluated first.
- Future image-format compatibility should be driven by Clonezilla's established
  image metadata and command behavior, not by a newly invented feclora format.
