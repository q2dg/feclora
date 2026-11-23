# Btrfs send-stream manifest contract

Feclora uses a dedicated manifest for Btrfs subvolume replication streams.
It is intentionally separate from block-image manifests: a `btrfs send` stream
is not a RAW filesystem image and must be restored with `btrfs receive`.

Schema version 1 records:

- The source filesystem UUID, subvolume ID and UUID, subvolume name and Btrfs
  device count.
- Full or incremental send mode and the optional incremental stream-parent
  UUID.
- Source snapshot ancestry (`parent_uuid`) and received-stream provenance
  (`received_uuid`).
- The stored stream filename, exact stored byte count and SHA-256.
- The stream compression (`none`, `gzip`, `xz`, `zstd` or `lz4`) and
  encryption (`none` or `age`).

The stream filename is a basename; the manifest contains no commands or
destination paths. The digest and byte count describe the stored representation
after compression and, when enabled, age encryption. A receiver validates
those values before decrypting or decompressing the stream.

A full stream has no stream parent. An incremental stream must identify the
read-only parent subvolume UUID used to generate it. That UUID is distinct from
Btrfs snapshot ancestry (`parent_uuid`) and received-stream provenance
(`received_uuid`). The destination must already contain the matching
read-only received parent before an incremental stream can be applied.

Older schema-v1 manifests that omit the `compression` or `encryption`
properties retain their backward-compatible defaults of `none`.

The manifest contract does not itself implement capture or restore.
`btrfs receive` may leave a partially received subvolume after failure; the
receiver keeps that result in private staging and must not report it as a
completed restore or publish a success marker until provenance verification
succeeds.
