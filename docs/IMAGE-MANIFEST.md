# Image manifest schema v1

feclora stores an image as a directory of artifacts plus a validated
`manifest.json`. The manifest is descriptive metadata, not an executable
restore plan. It never contains a target device path, shell command, or
arbitrary output path.

## Supported metadata

- `image_type`: whole `disk`, individual `partition`, or a descriptive `logical_volume` image (schema support only; no LV capture/restore engine yet).
- Source capacity and logical sector size (512 or 4096 bytes).
- Partition table type: GPT, MBR, none, or unknown.
- Artifact filename, semantic role, encoding, compression, byte length and
  SHA-256 digest.
- Partition identifier for partition-image artifacts.
- Recognized filesystem type for partition-image and logical-volume-image artifacts when known; Partclone restore uses it to select the matching executable. Older manifests without this optional field remain readable, but a Partclone restore cannot select a utility without it.
- Optional `storage` provenance: explicit byte scope and source layer, LUKS2 UUID, LVM VG/LV identities, Btrfs filesystem/subvolume UUID provenance and dependency identities. This is descriptive only; it never activates, unlocks, mounts, snapshots or modifies storage. Btrfs remains a filesystem-level image (using `partclone.btrfs` when supported); subvolume UUIDs are provenance metadata, not separate subvolume image artifacts.

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
- `logical-volume-image`: reserved for a filesystem-aware Partclone stream or raw LV byte stream. Its manifest requires storage provenance and does not imply that capture or restore execution is available.

Compression is declared per artifact: none, gzip, zstd, xz or lz4. The writer
must record the actual stored-file size and SHA-256 of the stored bytes. Restore paths verify the complete stored artifact and decompression stream before opening a target block device.

## Integrity, signatures and encryption

Schema v1 is currently written by local whole-disk and partition capture.
Disk and partition restore paths consume manifests. The schema can describe
logical-volume images and storage provenance, but no LV capture/restore engine
or Cockpit selection workflow is implemented. Repository publication uses the
manifest as its final commit marker. Legacy manifests without the optional
`storage` object remain readable.

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
