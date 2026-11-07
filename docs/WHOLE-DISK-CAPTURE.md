# Whole-disk capture

`feclora.storage.disk_capture.capture_disk` creates a raw whole-disk image,
an `sfdisk --dump` partition-table artifact, and a validated v1 manifest.

The whole disk is captured with generic `dd if=DEVICE bs=4M status=none`.
This deliberately does not use Partclone: Partclone is filesystem-aware and
is used for individual supported partitions, while a raw disk stream preserves
partition tables, boot sectors, gaps and all remaining sectors. Compression
may be none, gzip or xz.

Disk geometry and partition-table type are read from `lsblk`; table contents
come from `sfdisk --dump`. If no table is reported, an explanatory metadata
artifact is written and the manifest records `none`. Unknown table types are
preserved as `unknown`.

All payloads are staged in a private directory. The manifest is validated
before publication. Payload artifacts are hard-linked into the repository,
then the manifest is published last as the commit marker. If publication
fails, names created by this transaction are removed. Existing files are
never replaced.

This implementation is read-only with respect to the source device. It does
not yet implement mounted/busy-source checks, source revalidation, capture
progress, cancellation, restore, or power-loss recovery for a crash between
individual hard-link operations. The manifest-last convention lets readers
ignore incomplete image sets without a manifest.
