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

Artifact names are restricted to safe basenames. Duplicate names, unknown
fields, unsupported versions, invalid digests and inconsistent disk/partition
metadata are rejected.

## Artifact roles and formats

- `partition-table`: raw textual metadata from a generic partition-table tool
  such as `sfdisk`; not a block-device image.
- `disk-metadata`: descriptive source metadata.
- `boot-area`: raw boot-area bytes where explicitly captured and documented.
- `partition-image`: filesystem-aware Partclone stream or raw byte stream.

Compression is declared per artifact: none, gzip, zstd, xz or lz4. The writer
must record the actual stored-file size and SHA-256 of the stored bytes. A
future restore path must verify the complete artifact before opening a target
block device.

## Important limitations

Schema v1 does not yet define a writer, repository transaction, signature,
encryption, partition geometry map, or restore implementation. SHA-256 detects
accidental corruption only; it does not authenticate the manifest. A later
signed manifest and authenticated repository protocol are required before
untrusted network images can be accepted.
