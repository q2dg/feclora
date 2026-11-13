# Filesystem reduction strategies for proportional restore

Status: research checkpoint, not an implementation or compatibility guarantee.

Feclora's proportional GPT planner is deliberately narrower than its
Partclone capture/restore support. A filesystem being clonable or restorable
does not mean its on-disk allocation structures can be reduced safely.

## Current planner boundary

The current read-only planner can use filesystem minimum-size estimates for
ext2/3/4 and NTFS. It preserves partition starts and can shorten only the
last partition. The current NTFS probe uses `ntfsresize --info`; the ext
probe uses `e2fsck -n` and `resize2fs -P`. These are planning estimates,
not guarantees that a later staged shrink will succeed.

No source image or original source disk may be modified. Any future
filesystem transformation must run against a private staging copy and must
complete its filesystem check, geometry check and GPT validation before the
destination disk is touched.

## Findings

| Filesystem | Direct reduction | Alternative | Feclora decision |
|---|---|---|---|
| XFS | No supported in-place shrink command | Rebuild a new, smaller XFS filesystem and copy files with an XFS-aware dump/restore workflow | Do not treat as a block-level shrink. Evaluate a separate filesystem-migration executor. |
| F2FS | Upstream `resize.f2fs` documents a shrink-specific safe-resize option (`-s`), but its same manual page also says the current version only supports expanding a prebuilt filesystem | A version-specific staged shrink may be possible; exact tool/kernel behavior must be demonstrated | Research candidate only. Do not enable in the planner until the Fedora-packaged version, minimum-size behavior and round-trip integrity are tested. |
| exFAT | GParted's current feature matrix marks shrink unsupported; standard `exfatprogs` provides create/check/inspect/tune tools but no filesystem shrink utility | Create a new, smaller exFAT filesystem and copy files | Do not treat as a block-level shrink. Evaluate a separate file-copy migration, with explicit metadata/fidelity limits. |

### XFS

XFS cannot be reduced in place with `xfs_growfs` or the standard
xfsprogs toolchain. GParted documents a distinct copy-based route: it creates
a destination filesystem and copies the contents using `xfsdump` and
`xfsrestore`. This is a filesystem migration, not a resize of the original
filesystem and not a byte-preserving partition clone.

A Feclora implementation would need a new destination filesystem, explicit
preservation rules for ownership, ACLs, extended attributes, SELinux labels,
hard links, sparse files, quotas and XFS-specific metadata, followed by
independent verification. It must never be silently substituted for the
existing raw/Partclone restore path.

### F2FS

The upstream `resize.f2fs` manual includes `-s`, described as a safe-resize
option usable only with shrink resize. However, the same manual still states
that the current version only supports expanding a prebuilt filesystem.
That inconsistency is material: the presence of a shrink flag is not enough
to claim that a given released binary can shrink a real filesystem.

Before enabling F2FS, Feclora needs to identify the exact Fedora package
version and prove, on disposable images, that the binary can shrink; determine
how it calculates or validates the minimum; run `fsck.f2fs` before and after;
and verify file contents and filesystem geometry after the staged operation.
Until then F2FS remains fixed-size in proportional planning.

### exFAT

The current GParted feature matrix marks exFAT shrink as unsupported.
The standard `exfatprogs` tool set documents formatting, checking,
inspection, labels and tuning, but no shrink command.

A file-copy migration is technically different: create a smaller exFAT
filesystem, copy the files, then verify every file and the required attributes.
Feclora would need to define how it handles timestamps, hidden/system flags,
case behavior, naming constraints and any metadata that cannot be represented
or preserved. It must not be advertised as a lossless block-level shrink.

## Implementation gates

1. Keep XFS, F2FS and exFAT fixed-size in the current proportional GPT
   planner until their distinct execution paths exist.
2. Do not infer minimum filesystem size from free-space counters alone.
3. For any new adapter, operate only on a private staging copy, never the
   source artifact or source disk.
4. Re-run the filesystem-native checker after transformation and verify the
   resulting partition size does not exceed the planned GPT extent.
5. Add disposable-image tests for success, full/fragmented filesystems,
   corrupt metadata, missing tools, interrupted operations and read-back.
6. Keep block-preserving shrink and file-level migration as separate,
   explicitly selected strategies in API, UI and reports.

## References

- GParted filesystem feature matrix:
  https://gparted.org/features.php
- XFS dump/restore copy behavior (GParted feature notes):
  https://gparted.org/features.php
- Upstream F2FS resize.f2fs manual:
  https://kernel.googlesource.com/pub/scm/linux/kernel/git/jaegeuk/f2fs-tools/+/refs/heads/master/man/resize.f2fs.8
- exfatprogs upstream utilities and documented command set:
  https://github.com/exfatprogs/exfatprogs
