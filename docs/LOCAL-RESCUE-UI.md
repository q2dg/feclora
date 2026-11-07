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
user's home directory. Block-device imaging commands and process-use checks
run through non-interactive sudo. The Kickstart grants the live wheel user
passwordless sudo, while the UI and image repository remain owned by that user.

Whole-disk and partition capture show live byte progress and can be cancelled;
raw whole-disk and raw partition restores show write progress and can be
cancelled. Partclone partition restore still lacks live progress/cancellation.
Whole-disk restore reads the destination back and verifies its SHA-256 after a
successful write. Persistent per-operation logs, Partclone restore progress,
partition read-back verification, and full recovery from power loss remain
future work. Use disposable test disks until the BIOS/UEFI VM acceptance tests
and real hardware validation are complete.
