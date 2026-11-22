---
layout: default
title: Partition capture orchestration
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

![Illustrative partition capture workflow]({{ '/assets/mockups/partition-workflow.svg' | relative_url }})

*Illustrative mockup — not a screenshot. It summarizes the supported single-partition capture scope.*


# Partition capture orchestration

`feclora.storage.partition_image_capture.capture_partition_image` creates a manifest-backed image of one existing partition. It requires a current structured storage inventory; missing or unresolved layer information fails closed. The lower-level `feclora.storage.capture` module provides the read-only source checks and Partclone/raw process runner.

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

## Optional read-only pre-capture filesystem preflight

The privileged Textual API exposes `check_capture_filesystem` with exactly
`source` and `filesystem` parameters. It currently supports offline ext2/3/4, NTFS/ntfs3 and XFS sources. ext uses `blkid`, `e2fsck -f -n`,
`dumpe2fs`, `resize2fs -P` and `blockdev`; NTFS uses `blkid`,
`ntfsresize --info` and `blockdev`; XFS uses `blkid`, `xfs_repair -n` and
`blockdev`. All three reuse the source-safety checks and
refuse mounted, busy, root-backed or otherwise unverifiable devices. The API
returns the estimated minimum filesystem size for ext/NTFS or the checked
partition capacity for XFS, and identifies the read-only probe used. It never repairs or writes to the source.

The Textual partition-capture form offers an optional read-only preflight
for detected ext2/3/4, NTFS/ntfs3 and XFS sources. The user explicitly starts it;
capture remains available without running it. The
selected source and filesystem are bound to the result; changing the source
invalidates the check. Unsupported or unknown filesystem types are explicitly
identified and are not passed to an unrelated checker. A clean probe
does not provide application-level snapshot consistency.

## Process and publication safety

- The source must resolve to a block device (unless a test-only validator is
  injected); source is read by the external utility, never opened for writing.
- Arguments are passed as an argv array; no shell or shell pipeline is used.
- Standard input is closed. Standard output is streamed into the artifact
  writer. Standard error goes to a temporary file to avoid pipe deadlocks. A progress
callback counts bytes read; raw capture reports a percentage when source size
is known, while Partclone capture reports bytes without guessing its final size.
Cancelling the Textual operation stops the producer and prevents publication.
- Output is first written in a private staging directory beneath the repository.
  A non-zero producer exit prevents publication and staging data is discarded.
- A successful artifact is hard-linked into its final name; an existing name
  is never replaced.

## Manifest-backed image capture

## Scope and operator procedure

This workflow captures one partition only. It does not capture a partition
table or whole-disk boot areas, create a destination partition, resize a
filesystem, or provide a coordinated multi-device Btrfs snapshot. Multi-device
Btrfs sources are rejected rather than partially imaged. A single-device
Btrfs partition can be captured with `partclone.btrfs` when the required
inventory identifies its filesystem UUID and device membership.

A raw LUKS2 container is captured byte-for-byte only after `cryptsetup`
verifies its version-2 header and UUID. LUKS1 and unknown headers fail closed
for layer-aware capture. No passphrase or key is read. An opened crypt mapping
may appear in topology inventory, but a dedicated mapping-image capture
workflow is not exposed. LVM logical volumes use the separate manifest-backed
LV capture workflow documented in [the image manifest guide](IMAGE-MANIFEST.html).

In Textual's **Operations** workflow, choose partition capture, select the
source partition, enter a unique image identifier, choose compression and
optional image protection, and review the operation summary. The source is
read-only. Monitor streamed progress; cancelling stops the producer and
prevents publication. Verify that the manifest appears in image inventory
before attempting restore.

Illustrations may be real screenshots from a version-matched build or clearly
labeled mockups. A mockup is not evidence of runtime acceptance; see the
[screenshot and mockup policy](assets/screenshots/README.md).

Fedora 45's runtime package set also includes `e2fsprogs`, `xfsprogs`,
`ntfs-3g`, `dosfstools`, `exfatprogs` and `f2fs-tools`, which provide the
read-only post-restore checkers used by the filesystem map. Capability
inventory reports checker presence separately from Partclone presence; a
missing checker rejects Partclone restore before target writes.

Partclone and dd command semantics are based on the upstream Partclone usage documentation.
