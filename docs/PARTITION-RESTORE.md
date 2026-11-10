# Partition restore

`feclora.storage.partition_restore.restore_partition` restores a single
partition-image manifest to an existing partition device.

Before starting a writer it:
- requires the exact confirmation `ERASE /dev/PARTITION`;
- validates the manifest and requires exactly one partition-image artifact;
- verifies the stored artifact size and SHA-256;
- fully decompresses the image into a private temporary file on the local
  temporary filesystem, validating gzip/xz framing or zstd/lz4 process exit
  status before any target write. Encrypted artifacts are first authenticated
  and decrypted into a separate local temporary file;
- checks that the destination is a real block device of type `part`, large
  enough for the source geometry, and has the same logical sector size;
- rejects mounted, active-swap, busy, device-mapper-held, or Live-root backing
  destinations using lsblk, fuser, /proc/swaps and sysfs checks;
- repeats target identity, geometry and safety checks immediately before the
  restore utility starts.

Raw partition artifacts are written with `dd`. Partclone artifacts use the
filesystem-specific `partclone.* -r` executable recorded in the manifest.
The image stream is fully staged and verified before either writer starts.
Partclone is invoked with forced one-second progress updates; its stderr
percentage reports are forwarded to the Cockpit operation progress display. Cancelling the operation
terminates the active restore process. Raw restores report byte progress.

After a raw restore, feclora reads the exact source byte count back from the
destination with dd and compares SHA-256 against the staged image. After a
Partclone restore, feclora runs a filesystem-specific read-only sanity or
consistency check (for example e2fsck -f -n for ext filesystems or
xfs_repair -n for XFS). For NTFS, ntfsfix --no-action is only a limited check;
it is not equivalent to Windows chkdsk. These checks do not establish
byte-for-byte identity with the source. The required checker must be installed
before the Partclone writer is allowed to start.

Supported outer compression is none, gzip, xz, zstd and lz4. The zstd/lz4
codecs are decoded through the installed system CLI tools. Partition-table
creation/resizing and crash recovery are not implemented. The
destination partition must already exist and be at least as large as the source.

A successful restore also requires the applicable post-write verification to
pass. The Partclone consistency check is not a content-identity proof. Neither
verification mode is a substitute for boot validation. A failure after the
writer starts can leave the destination partially overwritten.
