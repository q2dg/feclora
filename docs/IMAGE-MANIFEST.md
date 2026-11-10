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

## Integrity, signatures and encryption

Schema v1 is written by local whole-disk and partition capture. Both disk and
partition restore paths consume manifests. Repository publication uses the
manifest as its final commit marker.

SHA-256 covers the exact stored bytes of each artifact. For an age-encrypted
artifact, this is the ciphertext digest: restore verifies the stored size and
digest first, then age authenticates and decrypts into private local staging
before decompression or target writes.

A detached `.minisig` file may sign the completed manifest. When present,
restore must verify it against a public key trusted independently of the image
repository; a present but unverifiable signature blocks restoration. Unsigned
images remain supported for local workflows and authenticated mTLS deployment
sessions. In those cases, the manifest's authenticity comes from the
independently authenticated local operator/repository or TLS control session,
not from SHA-256 alone.

SHA-256 detects artifact corruption but does not authenticate a manifest or
its publisher. Do not accept an unsigned manifest from an untrusted source
without a separate authenticated channel or trust decision. Full partition
geometry maps and crash-recovery journaling for repository publication remain
outside schema v1.
