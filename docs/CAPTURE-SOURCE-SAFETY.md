# Capture and restore target safety

Partition capture, whole-disk capture, partition restore and whole-disk restore
use `feclora.storage.source_safety.check_capture_source_safe` as their default
source/target gate.

The gate:
- queries `lsblk` for the selected device and rejects mounted filesystems in
  its reported device subtree;
- checks active swap entries in `/proc/swaps`;
- invokes `fuser` for each block device in the selected subtree and rejects
  devices in use by a process;
- checks sysfs device-mapper holder directories;
- queries the inverse block-device graph to find physical disks backing the
  selected partition or logical device;
- resolves the live root through `findmnt` and `lsblk`; for overlay/squashfs
  roots it conservatively protects all disks backing currently mounted block
  devices, including the Live boot medium;
- fails closed if required commands, JSON metadata, swap information, or root
  dependency information cannot be obtained.

Capture re-runs the source gate immediately before starting Partclone or dd.
Restore validates the target type, capacity and logical sector size, verifies
the stored artifact hash and decompression stream, then repeats target checks
immediately before starting the writer.

## Remaining safety boundaries

This is not a complete concurrency or namespace proof. It cannot eliminate
races where another process mounts or opens a device after the final check.
Mounts in other namespaces may not be represented by the current lsblk view;
fuser and sysfs holder checks reduce but do not eliminate that risk. Swap
backing files, unusual loop/overlay backing chains, multipath, hardware RAID,
and storage stacks not fully exposed by lsblk need dedicated handling.

No destructive operation is enabled merely by this gate: the UI separately
requires an exact `ERASE /dev/DEVICE` confirmation for restores. Capture is
read-only. Use disposable devices until the virtual-machine and hardware
acceptance matrix has been completed.
