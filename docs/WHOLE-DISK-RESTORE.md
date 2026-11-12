# Whole-disk restore

feclora implements whole-disk restore in
`feclora.storage.disk_restore.restore_disk`.

It accepts a schema-v1 disk manifest and exactly one raw `disk-image`
artifact. The destination may be equal to or larger than the source image; a
smaller destination is rejected. The logical sector size must match.

Before starting the writer it:

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

The additional destination capacity is left unallocated. feclora does not
silently resize partitions or filesystems during a raw whole-disk restore.
MBR and unpartitioned images retain their original layout; GPT repair is only
performed after the source-sized byte range has passed read-back verification.

The writer uses generic `dd of=TARGET bs=4M conv=fsync status=none`. Raw,
gzip, xz, zstd and lz4 disk artifacts are supported. The Cockpit Operations wizard displays write
progress and supports cancellation; a cancellation can leave a partially
overwritten target. Read-back verification runs after a successful write.
Capture/restore operation events are persisted in the append-only operation
journal.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Tests use mocked device I/O. No VM or hardware restore has been validated.
Never test against a disk containing needed data.

Illustrations may be real screenshots from a version-matched build or clearly labeled mockups. A mockup is not evidence of runtime acceptance; see the [screenshot and mockup policy](assets/screenshots/README.md).

Age decryption staging uses the local system temporary filesystem, not the source repository, so a read-only remote repository can be used. Ensure the local temporary filesystem has enough free space for the decrypted artifact.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.