# Btrfs subvolume send/receive

Feclora now has a dedicated `btrfs send`/`btrfs receive` engine and durable
operation actions for subvolume capture and receive. This is distinct from the
existing single-device Btrfs partition-image path.

Capture accepts a subvolume directory and optional read-only incremental
parent. A writable source is snapshotted read-only in a temporary sibling
directory; the stream is written to private repository staging, hashed, and
published with its manifest last. The temporary snapshot is deleted after the
send attempt. The first implementation writes uncompressed streams only.

Receive verifies the stream size and SHA-256 before invoking Btrfs. Incremental
receive requires the matching read-only received parent within the selected
destination filesystem. Incoming data is received into a hidden staging
directory on that filesystem. The resulting subvolume's name and received UUID
must match the manifest before it is renamed into its final location. A failed
receive or failed provenance check leaves staging quarantined and is not
reported as a completed restore.

The destination Btrfs filesystem must already exist and be mounted at the
selected directory. Feclora does not create filesystems, mount targets, or
reconcile multi-device topology during this operation. Compression, encryption,
and interactive UI selection are not yet exposed for send streams.
