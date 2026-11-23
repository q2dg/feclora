# Btrfs send-stream manifest contract

Feclora uses a dedicated manifest for Btrfs subvolume replication streams.
It is intentionally separate from block-image manifests: a `btrfs send` stream
is not a RAW filesystem image and must be restored with `btrfs receive`.

The manifest records source filesystem and subvolume identity, Btrfs device
count, stream mode, optional incremental parent UUID, source snapshot
ancestry/provenance, compression and encryption modes, and the exact stored
stream size and SHA-256. The stream filename is a basename; the manifest does
not contain commands or destination paths.

A full stream has no stream parent. An incremental stream identifies the
read-only parent subvolume UUID used to generate it. That UUID is distinct
from Btrfs snapshot ancestry (`parent_uuid`) and received-stream provenance
(`received_uuid`). The destination must already contain the matching received
parent before an incremental stream can be applied.

The size and digest describe the final stored bytes, including compression
and, when enabled, age encryption. Receive validates those stored bytes before
decrypting and decompressing the stream for `btrfs receive`. Legacy manifests
that omit the encryption field are interpreted as unencrypted; compression
defaults to `none`.

A receiver must keep partial receives in private staging. It must not report a
restore as complete or publish the subvolume at its final destination until
the received name and provenance have been verified.
