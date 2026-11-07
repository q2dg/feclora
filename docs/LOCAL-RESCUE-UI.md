# Local rescue UI

The Local rescue mode now exposes:
- disk and partition inventory;
- whole-disk capture;
- partition capture with Partclone when the filesystem-specific executable
  exists, otherwise raw dd;
- restore of disk or partition manifests from `/home/feclora/images`.

The UI requires a unique image identifier. Restore requires typing the exact
phrase `ERASE /dev/DEVICE`; cancelling or entering a different phrase does not
start a writer. The image repository is created with mode 0700 in the live
user's home directory.

The interface currently runs imaging synchronously and reports completion or
errors in a dialog. Progress bars, cancellation controls, per-operation log
files, target read-back verification, and full recovery from power loss remain
future work. Use disposable test disks until the BIOS/UEFI VM acceptance tests
and real hardware validation are complete.
