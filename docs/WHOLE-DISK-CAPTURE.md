# Whole-disk capture

`feclora.storage.disk_capture.capture_disk` creates a raw whole-disk image,
an `sfdisk --dump` partition-table artifact, and a validated v1 manifest.

The whole disk is captured with generic `dd if=DEVICE bs=4M status=none`.
This deliberately does not use Partclone: Partclone is filesystem-aware and
is used for individual supported partitions, while a raw disk stream preserves
partition tables, boot sectors, gaps and all remaining sectors. Compression
may be none, gzip, xz, zstd or lz4. zstd and lz4 use the installed system
executables; the selected compression level is recorded in the manifest.

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
mounted/busy/root-backed sources and revalidates before reading. The Cockpit Operations wizard shows byte-based progress and supports cancellation; a cancelled capture removes its staging data and does not publish a manifest. Power-loss recovery for a crash
between individual hard-link operations remains pending. The manifest-last convention lets readers
ignore incomplete image sets without a manifest.

## Cockpit operator procedure

1. Open Cockpit's **Operations** workflow and select whole-disk capture.
2. Select the source disk and enter a unique image identifier. The operation reads the source; it does not modify it.
3. Choose compression (`none`, `gzip`, `xz`, `zstd` or `lz4`) and, when applicable, its level.
4. Choose image protection independently: neither, age encryption, minisign signature, or both. Supply only the public age recipients file and/or the minisign secret key requested by the selected mode. These options are not prerequisites for ordinary capture.
5. Review the operation summary and start capture. Monitor streamed progress. Cancelling prevents publication of a valid manifest; do not use a partial artifact set.
6. Confirm that the manifest appears in the image inventory before using or transferring the image.

**Screenshots are pending.** Follow the [Cockpit screenshot capture plan](assets/screenshots/README.md). The repository currently has no validated Cockpit screenshot set. Capture each step from a real, version-matched Fedora Live build and store it under `docs/assets/screenshots/`; clearly labeled mockups are acceptable when real screenshots are unavailable; see the screenshot and mockup policy.
