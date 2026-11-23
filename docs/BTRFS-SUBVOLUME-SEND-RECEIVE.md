# Btrfs subvolume send/receive

Feclora provides a dedicated `btrfs send`/`btrfs receive` workflow for
subvolume replication. It is separate from block-level Btrfs partition
imaging: a send stream is not a RAW filesystem image and must be applied with
`btrfs receive`.

## Capture

The capture operation accepts a subvolume directory and an optional read-only
incremental parent. A writable source is snapshotted read-only in a temporary
sibling directory; an already read-only source is used directly. Nested
subvolumes are rejected so their contents are never silently omitted.

The stream can be stored with one of these compression modes:

- `none`: no compression
- `gzip`, `xz`, `zstd` or `lz4`

Capture can also encrypt the stored stream with `age`. Compression is applied
before encryption. The stored byte count and SHA-256 cover the final artifact
(as stored in the repository), and the manifest records the compression and
encryption modes. Encryption is optional and requires configured age
recipients. The Textual capture form exposes the compression selector and
encryption toggle.

The stream is written to private repository staging and published with its
manifest last. A temporary read-only snapshot is removed after the send
attempt. Incremental streams identify the read-only parent UUID used for
`btrfs send -p`.

## Receive

Receive verifies the stored stream size and SHA-256 before invoking Btrfs. If
the manifest marks the stream as encrypted, Feclora decrypts it with the
configured age identity; it then decompresses the stream according to the
manifest before passing it to `btrfs receive`. The receiver therefore consumes
the same compression/encryption metadata that capture published.

For encrypted streams, the receiver looks for the server identity at
`/etc/feclora/pki/server.age` and/or the client identity configured by the
deployment-client settings. Capture recipients are read from
`/etc/feclora/pki/age-recipients.txt` unless the client configuration supplies
a recipients file. Private identity files must remain root-owned and
inaccessible to group/other users.

Incremental receive requires the matching received parent within the selected
destination filesystem. Incoming data is received into a hidden staging
directory on that filesystem. Before publication, the resulting subvolume's
name and received UUID must match the manifest; only then is it renamed to its
final location. Failed or unverifiable receives remain quarantined and are not
reported as completed restores.

## Boundaries

The destination Btrfs filesystem must already exist and be mounted at the
selected directory. Feclora does not create filesystems or mount targets, and
this workflow does not reconcile multi-device block topology. The repository
must be filesystem-backed; S3 object-repository publication is not supported
for Btrfs send streams.

The existing Btrfs partition-image path remains a separate, single-device
block-imaging capability. This subvolume workflow supports full and incremental
streams but does not provide coordinated multi-device block-image capture or
profile-aware layer restore.

See the [send-stream manifest contract](BTRFS-SEND-MANIFEST.md) for the
persistent metadata and provenance rules.
