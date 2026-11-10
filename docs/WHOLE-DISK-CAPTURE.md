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

This implementation is read-only with respect to the source device. It checks
mounted/busy/root-backed sources and revalidates before reading. The TUI shows
byte-based progress and supports cancellation; a cancelled capture removes its
staging data and does not publish a manifest. Power-loss recovery for a crash
between individual hard-link operations remains pending. The manifest-last convention lets readers
ignore incomplete image sets without a manifest.

## Local rescue UI procedure

1. Open **Capture whole disk** and select the source disk. The operation is read-only.
2. Enter a unique image identifier.
3. Choose compression (`none`, `gzip`, `xz`, `zstd` or `lz4`) and, when applicable, its level.
4. Choose image protection independently: neither, age encryption, minisign signature, or both. Supply only the public age recipients file and/or the minisign secret key requested by the selected mode.
5. Review the source and wait for the progress gauge to complete. Closing the gauge cancels capture; an incomplete set is not published as a valid image.
6. Confirm that the manifest appears in the image repository before using or transferring the image.

The UI currently uses the text-mode `dialog` interface. **Screenshots are intentionally not embedded yet**: they must be captured from a real, version-matched Fedora Live session. Add them under `docs/assets/screenshots/` with the same step numbers before claiming visual validation.
