# Image manifest schema v1

feclora stores an image as a directory of artifacts plus a validated
`manifest.json`. The manifest is descriptive metadata, not an executable
restore plan. It never contains a target device path, shell command, or
arbitrary output path.

## Supported metadata

- `image_type`: whole `disk` or individual `partition`.
- Source capacity and logical sector size (512 or 4096 bytes).
- Partition table type: GPT, MBR, none, or unknown.
- Artifact filename, semantic role, encoding, compression, byte length and
  SHA-256 digest.
- Partition identifier for partition-image artifacts.
- Recognized filesystem type for partition-image artifacts when known; Partclone restore uses it to select the matching executable. Older manifests without this optional field remain readable, but a Partclone restore cannot select a utility without it.

Artifact names are restricted to safe basenames. Duplicate names, unknown
fields, unsupported versions, invalid digests and inconsistent disk/partition
metadata are rejected.

## Artifact roles and formats

- `partition-table`: raw textual metadata from a generic partition-table tool
  such as `sfdisk`; not a block-device image.
- `disk-metadata`: descriptive source metadata.
- `boot-area`: raw boot-area bytes where explicitly captured and documented.
- `disk-image`: raw whole-disk stream (including raw fallback when filesystem-aware capture is unavailable).
- `partition-image`: filesystem-aware Partclone stream or raw partition byte stream.

Compression is declared per artifact: none, gzip, zstd, xz or lz4. The writer
must record the actual stored-file size and SHA-256 of the stored bytes. Restore paths verify the complete stored artifact and decompression stream before opening a target block device.

## Important limitations

Schema v1 is written by local partition and whole-disk capture. Both disk and partition restore paths consume manifests. Repository publication uses a manifest-last commit marker, but does not yet provide crash-recovery journaling, signatures, encryption, or full partition geometry maps. SHA-256 detects
accidental corruption only; it does not authenticate the manifest. A later
signed manifest and authenticated repository protocol are required before
untrusted network images can be accepted.
