# Partition capture orchestration

`feclora.storage.capture` provides a read-only capture planner and process
runner for one partition.

## Tool selection

Known filesystem types map to the corresponding Partclone executable
(`partclone.extfs`, `partclone.ext4`, `partclone.ntfs`, `partclone.xfs`,
`partclone.btrfs`, `partclone.fat`, `partclone.exfat`, or
`partclone.f2fs`). Fedora 45's `partclone` RPM provides these executables;
the package release is selected by Fedora updates rather than pinned by Feclora. The planner uses Partclone's documented clone mode,
`-c -s DEVICE`, with output directed to stdout. If no matching executable is
available, it uses generic `dd if=DEVICE bs=4M status=none` and labels the
artifact as raw. It never guesses that an unsupported filesystem is safe for
Partclone.

## Process and publication safety

- The source must resolve to a block device (unless a test-only validator is
  injected); source is read by the external utility, never opened for writing.
- Arguments are passed as an argv array; no shell or shell pipeline is used.
- Standard input is closed. Standard output is streamed into the artifact
  writer. Standard error goes to a temporary file to avoid pipe deadlocks. A progress
callback counts bytes read; raw capture reports a percentage when source size
is known, while Partclone capture reports bytes without guessing its final size.
Cancelling the Cockpit operation stops the producer and prevents publication.
- Output is first written in a private staging directory beneath the repository.
  A non-zero producer exit prevents publication and staging data is discarded.
- A successful artifact is hard-linked into its final name; an existing name
  is never replaced.

## Manifest-backed image capture

`feclora.storage.partition_image_capture.capture_partition_image` wraps the
capture engine and publishes a complete schema-v1 partition `ImageManifest`.
It records source size, logical sector size, filesystem and the raw or
Partclone artifact. It supports none, gzip, xz, zstd and lz4 outer compression.
When requested, age encryption is applied after compression and minisign signs
the completed manifest. Encryption and signing are independent optional
choices; neither is required for an ordinary unsigned, unencrypted image.

## Scope and operator procedure

This workflow captures one partition only. It does not capture a partition
table or whole-disk boot areas, create a destination partition, resize a
filesystem, or provide a coordinated multi-device Btrfs snapshot. Multi-device
Btrfs sources are rejected rather than partially imaged.

In Cockpit's **Operations** workflow, choose partition capture, select the
source partition, enter a unique image identifier, choose compression and
optional image protection, and review the operation summary. The source is
read-only. Monitor streamed progress; cancelling stops the producer and
prevents publication. Verify that the manifest appears in image inventory
before attempting restore.

**Screenshots are pending.** Follow the [Cockpit screenshot capture plan](assets/screenshots/README.md). Capture the workflow from a real, version-matched
Fedora Live build and store the images under `docs/assets/screenshots/`. Do not
substitute mockups or screenshots from a different UI revision.

Fedora 45's runtime package set also includes `e2fsprogs`, `xfsprogs`,
`ntfs-3g`, `dosfstools`, `exfatprogs` and `f2fs-tools`, which provide the
read-only post-restore checkers used by the filesystem map. Capability
inventory reports checker presence separately from Partclone presence; a
missing checker rejects Partclone restore before target writes.

Partclone and dd command semantics are based on the upstream Partclone usage documentation.
