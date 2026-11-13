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
| F2FS | The current upstream `resize.f2fs` manual explicitly says the current version only supports expanding a prebuilt filesystem. Its `-s` option description ("safe resize ... only ... w/ shrink resize") does not override that limitation. | Kernel documentation describes online-resize reservation concepts, but that is not proof that Feclora's userspace toolchain can safely shrink an offline image. | Not supported by the current offline shrink path. Keep fixed-size unless a concrete kernel/userspace interface is demonstrated and tested. |
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

The current upstream `resize.f2fs` manual explicitly states that the current
version only supports expanding a prebuilt filesystem. Although it lists
`-s` as a safe-resize option usable only with shrink resize, that flag alone
does not establish a supported shrink workflow. The kernel's current F2FS
documentation also describes online-resize reservation concepts; this is a
separate mechanism and must not be conflated with an offline image shrink.

Decision: F2FS remains fixed-size in Feclora's proportional planner. Revisit
only if a supported kernel/userspace operation is identified for the exact
Fedora runtime, with documented offline/online requirements, a reliable
minimum-size calculation, pre/post `fsck.f2fs`, and disposable-image
round-trip evidence.

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


## Concrete migration workflow proposals (not yet executable)

### XFS migration

1. Allocate a private staging workspace with sufficient space for both the
   source filesystem image and the destination filesystem image.
2. Create a new XFS filesystem sized to the planned partition extent.
3. Mount source read-only and destination with required XFS features/options.
4. Run `xfsdump` from the source and `xfsrestore` into the destination.
5. Explicitly preserve/restore quotas and verify ACLs, xattrs, SELinux labels,
   ownership, hard links, sparse files, special files and file contents.
6. Run `xfs_repair -n` against the unmounted destination; inspect geometry and
   filesystem UUID, then update the staged GPT only after validation.

This is not byte-identical. It can change filesystem UUID and internal
metadata; boot references and fstab/initramfs configuration may need updating.
The current Feclora whole-disk artifact path cannot silently substitute it.

### exFAT migration

1. Create a new exFAT filesystem in a private staging partition sized to fit.
2. Copy files with an exFAT-aware implementation that preserves supported
   timestamps, attributes and naming semantics.
3. Compare directory trees, file sizes and cryptographic hashes; run
   `fsck.exfat` on the unmounted destination.
4. Document any metadata that the source or destination implementation cannot
   preserve. Reject the migration if required metadata fidelity is unknown.

This is not a lossless block-level shrink. The standard exfatprogs command set
documents formatting, checking, inspection and tuning, not a shrink operation.
A third-party utility or a newer feature must not be trusted without code
review and disposable-media testing.

### Common safety boundary

Both migration strategies require a separate, explicit user-selected
"filesystem migration" mode. They must not be presented as normal proportional
restore or silently applied to raw/Partclone artifacts. They also require
source-to-destination file-level verification, updated filesystem identity
handling, boot configuration analysis, interruption-safe staging and an
atomic final publication step. Until those components exist, XFS and exFAT
remain fixed-size in the current planner.
