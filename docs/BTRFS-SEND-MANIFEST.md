# Btrfs send-stream manifest contract

Feclora uses a dedicated manifest for Btrfs subvolume replication streams.
It is intentionally separate from block-image manifests: a `btrfs send` stream
is not a RAW filesystem image and must be restored with `btrfs receive`.

The initial contract records the source filesystem UUID, subvolume ID and UUID,
Btrfs device count, stream mode, optional incremental parent UUID, source
snapshot ancestry/provenance, and the exact stored stream size and SHA-256.
The stream filename is a basename, and the manifest does not contain commands
or destination paths.

A full stream has no stream parent. An incremental stream must identify the
read-only parent subvolume UUID used to generate it. That UUID is distinct from
Btrfs snapshot ancestry (`parent_uuid`) and received-stream provenance
(`received_uuid`). The destination must already contain the matching
received parent before an incremental stream can be applied.

This contract does not itself implement capture or restore. In particular,
`btrfs receive` may leave a partially received subvolume after failure;
a receiver must keep that result in private staging and must never report it as
a completed restore or publish a success marker until verification succeeds.
