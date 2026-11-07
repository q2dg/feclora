# Capture source safety

Partition and whole-disk capture now call
`feclora.storage.source_safety.check_capture_source_safe` before starting an
imaging process.

The check:
- queries `lsblk` for the selected device and rejects any mounted filesystem
  in the returned device subtree;
- queries the inverse block-device graph to find the physical disk(s) backing
  a selected partition or logical device;
- resolves the live root mount through `findmnt` and `lsblk`, then rejects a
  source whose backing disk is part of that root dependency set;
- fails closed if required commands, JSON metadata, or root dependency
  information cannot be obtained.

This is not a complete busy-device detector. It does not yet inspect open file
descriptors, swap activation, other mount namespaces, containers, device
mapper holders beyond the graph reported by lsblk, or concurrent mount changes
between the check and process start. A production UI must re-run inventory and
safety checks immediately before capture and still treat races as possible.
Capture is not yet enabled in the TUI.
