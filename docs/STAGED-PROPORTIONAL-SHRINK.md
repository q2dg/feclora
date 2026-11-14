# Private staged filesystem shrinking

The proportional-image work now includes an offline ext2/ext3/ext4 shrink
primitive in `feclora.storage.staged_filesystem_shrink`.

`shrink_staged_ext_filesystem()` accepts only a `StagedRawDiskImage` private
regular file. It derives a byte offset and original partition byte limit from
the inspected GPT geometry, attaches that exact range with `losetup`, reads
back the loop mapping (backing file, offset and size limit), and checks that
the loop partition is not mounted or busy. It then verifies the filesystem
signature, runs a no-write `e2fsck`, reads the ext block geometry, invokes
`resize2fs` with the requested block count, runs the no-write checker again,
and verifies the resulting block count. The loop device is detached in a
`finally` path. The returned staging descriptor contains the verified current
SHA-256 digest (unchanged if the filesystem already fits and no resize occurs).

The function is deliberately limited:

- It does not open the original source disk or a destination disk for writing.
- It does not change the staged RAW file length or rewrite GPT.
- The caller must supply a target partition capacity already derived from a
  validated layout plan; the filesystem target must fit within that capacity.
- Only ext2/ext3/ext4 are supported by this executor. NTFS needs a separate
  executor and is not implicitly modified.
- A successful filesystem shrink is not a completed proportional restore.
  GPT rewrite, final staging validation, destination identity/capacity/sector
  revalidation, explicit destructive confirmation, destination write and
  read-back verification remain separate gates. No destination restore path
  is authorized by this primitive.

Automated test cases have been added with an injected command runner. They
exercise loop mapping validation, filesystem-type rejection, digest mismatch,
shrink command construction and detach behavior. These tests have not been
run as part of this change.


## NTFS staged shrink

NTFS has a separate executor in `feclora.storage.staged_ntfs_shrink`.
`shrink_staged_ntfs_filesystem()` applies the same private-RAW and exact-loop
mapping checks, verifies that the loop capacity matches the source partition
geometry, and requires an NTFS signature. It reads both the current volume
size and the live minimum reported by `ntfsresize --info`, rejects a target
outside those bounds, then runs `ntfsresize --size` without `--force`.
Finally it re-runs the information probe and checks the resulting volume
size before detaching the loop and returning the verified current digest (unchanged on a no-op).

The executor intentionally does not force a dirty or hibernated NTFS volume
through resize. Such a volume fails closed and must be made clean by an
operator using the appropriate Windows recovery/shutdown procedure before
capture is staged again. The executor still does not rewrite GPT, truncate
the RAW image, or write a destination disk.

NTFS unit tests use an injected command runner and cover the loop mapping,
filesystem signature, live minimum-size guard, source digest and detach path.
They have been added but not executed.


## Coordinated staging preparation

The coordinator in `feclora.storage.proportional_preparation` now joins these
primitives. It inspects the GPT inside the staged RAW file, matches every
planned partition by PARTUUID, verifies unchanged starts and partition types,
and permits at most one shortened partition (the final source partition).
For that partition it dispatches to the ext or NTFS executor; if the
filesystem already fits the planned partition, the executor performs its
read-only checks and leaves its bytes unchanged. The coordinator then calls
the private GPT rewrite routine, which relocates backup GPT metadata, truncates
the staged RAW to the requested size, and validates the rewritten GPT and
partition identities.

This is still a staging-only operation. It does not discover or approve a
destination device, request destructive confirmation, write a destination,
or perform destination read-back. The ISO is not built by this workflow.


## Destructive restore of prepared proportional staging

The new `feclora.storage.staged_proportional_restore` entry point restores a
prepared `StagedRawDiskImage` without fabricating or weakening an image
manifest. Before any destination write it verifies the private staging
directory and single-link file, opens the staging inode with no symlink
following, takes an exclusive file lock, checks its exact size and SHA-256,
and validates both GPT copies from the staged bytes.

The destination must be an accessible whole-disk device. Its capacity must
equal the staged image size exactly (larger disks are not silently accepted),
and its logical sector size must match the GPT geometry. The restore checks
that the target is not mounted, busy, held by device-mapper, active swap, or
backing the live root. It records the block-device identity and repeats
identity, geometry and safety checks immediately before writing. The caller must also supply the block-device identity captured when the target
was selected; the current identity must match it before any write. The operator
must provide the exact confirmation phrase `ERASE /dev/...`.

The writer streams from the already-open locked staging file to `dd` through
standard input; it never reopens the original repository artifact. After
writing, the same destination identity is checked again and the complete
staged byte range is read back and SHA-256 compared. A write or read-back
failure is reported as an unsuccessful restore; if writing began, the
destination may contain partially written or unverified data.

This API is deliberately separate from the existing manifest-based
`restore_disk()`. It does not resize or migrate the original source, does not
build an ISO, and does not introduce client authentication or a PXE proxy.
Automated tests cover confirmation, staging digest, exact capacity,
device-identity recheck, write/read-back flow and read-back mismatch. They
have been added but have not been executed.


## Interactive proportional restore workflow

The local rescue UI now exposes a separate proportional restore choice for
whole-disk GPT images. The operator selects the smaller destination and the
original source disk. The source must still be present, offline and unused:
its capacity and logical sector size must match the image, and its partition
PARTUUIDs, GPT type GUIDs, start sectors and byte capacities must match the
verified staged GPT exactly.

The inventory now requests PARTUUID, PARTTYPE, PARTLABEL and START from
`lsblk`. The workflow maps staged GPT entries to the selected source
partitions by PARTUUID, then runs the ext2/3/4 or NTFS minimum-size probes
read-only against those source partitions. Unsupported, unknown, mounted,
busy or inconsistent filesystems fail closed. The actual filesystem shrink
and GPT rewrite are performed only on the private RAW staging copy.

Before asking for the final destructive confirmation, the UI presents the
source, destination, resulting image size and each planned partition's
PARTUUID, start sector, planned sector count and minimum filesystem size.
Only after the exact `ERASE /dev/...` phrase is entered does the guarded
destination writer run. It also requires the destination's block-device
identity captured at selection time and rechecks it, capacity, sector size
and safety immediately before writing.

This interactive path is for proportional GPT restore only. It does not add
client authentication, a PXE proxy or an artifact relay. It does not modify
the original source disk or repository artifact. No ISO build is part of this
workflow. Tests have been added but have not been executed.


The proportional UI also compares the kernel block-device identities
(`st_rdev`) of the selected source and destination, not just their path
strings. This rejects aliases such as a `/dev/disk/by-id/...` path and
`/dev/sdX` that resolve to the same physical device. Immediately before the
destination write, it rechecks that the original source still has the same
identity and remains offline/unused; the destination writer independently
rechecks its captured identity, exact capacity, logical sector size and
source-safety state.
