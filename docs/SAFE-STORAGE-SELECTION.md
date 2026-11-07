# Safe storage selection

The storage-selection layer currently validates a **whole-disk clone plan only**.
It is deliberately separate from any imaging or write operation.

## Validation rules

- Source and target must be distinct, uniquely identified top-level disks in the
  current `lsblk` inventory. Partition paths and nested devices are not accepted.
- Both disks must have a known, positive byte capacity.
- The target must not be read-only and must be at least as large as the source.
- Any mounted filesystem anywhere in either disk's partition/device tree blocks
  selection. This conservative first iteration avoids inconsistent source reads
  and accidental writes to mounted target filesystems.
- A disk containing the live `/` filesystem is never selectable.
- Paths are resolved against the current inventory, not menu row numbers.

## Safety boundary

`validate_clone_selection()` returns an immutable data object describing the
validated pair. It does not open a device, call `dd`/Partclone, mount, unmount,
partition, format, or write anything. The result is **not** authorization to
execute a clone. The inventory can change after validation; any future execution
layer must recollect inventory and revalidate immediately before use, then add
explicit operator confirmation and further safeguards.

This first iteration intentionally does not infer device identity from model,
serial, or WWN: those fields can be absent or duplicated. The current `lsblk`
path must be unique in the supplied snapshot. A later execution layer should
add revalidation using kernel device identity (major/minor) and stable hardware
identifiers where available.
