# Partition restore

`feclora.storage.partition_restore.restore_partition` restores a single
partition-image manifest to an existing partition device.

Before starting a writer it:
- requires the exact confirmation `ERASE /dev/PARTITION`;
- validates the manifest and requires exactly one partition-image artifact;
- verifies the stored artifact size and SHA-256;
- fully decompresses the image into a temporary file on the image repository
  filesystem, validating gzip/xz framing before any target write;
- checks that the destination is a real block device of type `part`, large
  enough for the source geometry, and has the same logical sector size;
- rejects mounted, active-swap, busy, device-mapper-held, or Live-root backing
  destinations using lsblk, fuser, /proc/swaps and sysfs checks;
- repeats target identity, geometry and safety checks immediately before the
  restore utility starts.

Raw partition artifacts are written with `dd`. Partclone artifacts use the
filesystem-specific `partclone.* -r` executable recorded in the manifest.
The image stream is fully staged and verified before either writer starts.

Supported outer compression is none, gzip and xz. zstd/lz4 adapters, progress
reporting, cancellation, post-write read-back verification, partition-table
creation/resizing and crash recovery are not implemented. The destination
partition must already exist and be at least as large as the source.

A successful process exit means the imaging utility reported success; it is
not a substitute for boot and filesystem validation. A failure after the
writer starts can leave the destination partially overwritten.
