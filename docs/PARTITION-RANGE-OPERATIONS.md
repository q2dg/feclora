# Partition range operations

feclora's whole-disk image format stores the raw disk payload and an associated sfdisk partition-table snapshot. A partition can therefore be selected from an existing whole-disk image without first restoring the entire disk.

## Implemented core

`src/feclora/storage/partition_range.py` provides:

- Strict parsing of `sfdisk --json` with duplicate-key rejection.
- Conversion of partition start/size sectors into byte offsets and lengths.
- Bounds checks against the whole-disk image size.
- Duplicate-node and overlapping-range rejection.
- Exact selection by partition device node, PARTUUID or partition name; ambiguous selectors fail closed.
- Bounded `pread`/`pwrite` copying of a selected byte range, SHA-256 calculation, progress callbacks and cancellation.

## Integration still required

This is a tested low-level primitive, not yet a user-facing restore workflow. The caller must still:

1. Load and authenticate the image manifest and verify the whole-disk image digest before trusting its partition table.
2. Obtain the actual logical sector size and validate it against image metadata.
3. Present the partition list and require independent local target selection.
4. Run the existing mounted/root/system-device protections and destructive confirmation before opening the target.
5. Ensure the selected destination partition is large enough and compatible with the source partition's filesystem/content.
6. Read the destination back and compare SHA-256 before recording success.

Partition-to-partition cloning can reuse the same bounded copier with source offset zero and the source partition's exact byte length. Whole-disk-image-to-partition restore uses the selected partition's offset and length from the validated partition table. The code must never infer a destination from a remote image or remote host.

## Resizing policy

Raw partition-range copying does not resize filesystems. Disk layout planning must be a separate operation. Preserve-layout mode retains partition starts and sizes; proportional growth and selected-partition growth require a previewed, validated sector layout, followed by filesystem-specific growth tools and a final consistency check. EFI, BIOS boot, recovery, swap, LVM and LUKS partitions need explicit policies rather than blind proportional scaling.
