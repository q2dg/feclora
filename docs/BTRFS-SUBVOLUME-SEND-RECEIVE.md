# Btrfs subvolume send/receive

Feclora provides a dedicated `btrfs send`/`btrfs receive` engine and durable
local-operation actions for subvolume capture and receive. This workflow is
separate from Btrfs partition imaging: it stores a send stream, not a block
image of the filesystem.

## Capture

Capture accepts a subvolume directory, an image ID, a filesystem-backed image
repository and an optional read-only incremental parent. A writable source is
first snapshotted read-only in a temporary sibling directory. Nested
subvolumes are rejected because `btrfs send` would omit their contents.

The stream can be stored using one of these compression settings:

- `none`
- `gzip`
- `xz`
- `zstd`
- `lz4`

Age recipient encryption can be enabled independently of compression. When
enabled, Feclora compresses the stream first and encrypts the compressed
artifact afterwards. The capture controls are available in the Textual
operation form. Recipient keys must already be initialized; the API uses the
configured Feclora recipient material.

The stream is written to private repository staging. Feclora records the
stored artifact's exact byte count and SHA-256 in the dedicated manifest, then
publishes the stream and manifest as one image set. The manifest records the
selected compression and whether age encryption was applied. The temporary
read-only snapshot is removed after the send attempt.

## Receive

Receive verifies the stored stream's size and SHA-256 before invoking Btrfs.
For an age-encrypted stream, Feclora first decrypts it using a configured
identity. It then decompresses the plaintext stream and passes the result to
`btrfs receive`.

Incremental receive requires the matching read-only received parent within the
selected destination filesystem. The destination Btrfs filesystem must already
exist and be mounted at the selected directory. Incoming data is received into
a hidden staging directory on that filesystem. The resulting subvolume's name
and received UUID must match the manifest before it is renamed into its final
location. A failed receive or failed provenance check is not reported as a
completed restore; partial receive data is retained in staging for inspection.

The API resolves configured identities from the Feclora server identity and
the client runtime configuration when present. A stream encrypted with age
cannot be received unless at least one usable identity is configured.

## Boundaries

- The repository must be filesystem-backed. S3 object-repository publication
  is not supported for Btrfs send streams.
- The destination filesystem must already be mounted; Feclora does not create
  filesystems or mount targets.
- This workflow does not provision or reconcile multi-device Btrfs topology.
- It rejects nested subvolumes rather than attempting recursive orchestration.
- It is distinct from the existing single-device Btrfs partition-image path.

The implementation supports compression and age encryption. Codec-specific
round-trip and failure-path regression coverage is tracked separately from the
basic send/receive engine tests; do not infer that every codec combination has
been exercised solely from a passing general CI run.
