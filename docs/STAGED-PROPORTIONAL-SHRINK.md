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
`finally` path. The returned staging descriptor contains a fresh SHA-256
digest.

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
size before detaching the loop and returning a refreshed digest.

The executor intentionally does not force a dirty or hibernated NTFS volume
through resize. Such a volume fails closed and must be made clean by an
operator using the appropriate Windows recovery/shutdown procedure before
capture is staged again. The executor still does not rewrite GPT, truncate
the RAW image, or write a destination disk.

NTFS unit tests use an injected command runner and cover the loop mapping,
filesystem signature, live minimum-size guard, source digest and detach path.
They have been added but not executed.
