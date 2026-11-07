# Safe storage selection

The storage-selection layer validates a **whole-disk clone plan only**. It is
separate from every imaging or write operation.

## Validation rules

- Source and target must be distinct, uniquely identified top-level disks in
  the current `lsblk` inventory. Partitions and nested devices are rejected.
- Both disks need a known, positive byte capacity.
- The target must not be read-only and must be at least as large as the source.
- Any mounted filesystem in either disk's reported partition/device tree blocks
  selection.
- An independent live-root probe uses `findmnt` to identify the source mounted
  at `/`, then `lsblk --inverse` to trace device-mapper/LVM dependencies to
  their backing whole disks. Pass those paths as `protected_disk_paths` to
  `validate_clone_selection()`.
- If the root source cannot be resolved to one or more whole disks, the probe
  fails closed. Do not proceed with selection when the probe fails.

## Safety boundary

The probe runs only read-only metadata commands. The selection function returns
an immutable data object; it does not open block devices, invoke imaging tools,
mount/unmount, partition, format, or write. It is not authorization to clone.

The inventory and root-dependency graph are point-in-time snapshots. A future
executor must recollect and revalidate both immediately before use, verify
major/minor device identity, protect all mounted filesystems and system
dependencies, and require explicit operator confirmation.

## Current limitation

Some live environments expose the root filesystem as an overlay, squashfs,
loop device, or another non-`/dev` source. This initial root probe cannot
reliably trace every such arrangement and intentionally rejects unresolved
sources. Supporting those boot layouts requires a separately tested resolver;
it must not be worked around by disabling root protection.
