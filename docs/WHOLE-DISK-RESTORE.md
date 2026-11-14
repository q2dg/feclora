---
layout: default
title: Whole-disk restore
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">

# Whole-disk restore

<badge>Implemented in Cockpit</badge>

Feclora restores one verified raw whole-disk image to a whole-disk block
device. The destination is overwritten. A restore is not reversible and an
interruption can leave the destination partially written.

![Illustrative mockup of the destination review screen]({{ '/assets/mockups/restore-wizard.svg' | relative_url }})

<em>Illustrative mockup — not a screenshot. Device names, image IDs and capacities are fictional.</em>

## Before you start

- Confirm that the image manifest belongs to the intended source disk.
- Confirm that the complete artifact is present in the selected repository.
- Identify a destination disk whose contents may be destroyed.
- Compare model, capacity and stable identifiers such as WWN or serial; do
  not rely on a transient `/dev/sdX` name alone.
- The destination must be at least as large as the source image and use the
  same logical sector size.
- If the artifact is age-encrypted, have the configured identity file or
  symmetric passphrase available. Decryption is staged on the Live system's
  temporary filesystem, which must have enough free space.

Never use a production disk as a test target.

## Cockpit procedure

1. Open **Operations** and choose whole-disk restore.
2. Select the repository containing the image.
3. Select the disk image by its image ID and inspect its source size, logical
   sector size, partition-table type, compression and encryption metadata.
4. Select the destination disk. Re-check its model, capacity and identity.
5. Review the preflight result. Feclora rejects a target that is not a whole
   writable disk, is smaller than the image, has a different logical sector
   size, or fails the target-safety checks.
6. Read the destructive warning and type the exact confirmation requested:
   `ERASE /dev/DEVICE`, using the destination path displayed by Cockpit.
7. Start the operation. Do not disconnect the target or power off the system
   while the write and read-back verification are running.
8. Wait for the terminal result. A successful operation includes an
   independent read-back of the restored byte range and SHA-256 comparison.
9. If the destination is larger and the source uses GPT, Feclora relocates
   the backup GPT header to the end of the target and verifies the GPT
   structures. Additional capacity remains unallocated.

## What Feclora verifies

Before writing, the engine:

- loads and validates the versioned disk manifest;
- requires exactly one raw `disk-image` artifact;
- opens the repository and artifact without following symlinks;
- checks the stored artifact byte count and SHA-256 against the manifest;
- decrypts and authenticates age-protected artifacts when configured;
- fully decodes the compressed stream and checks that its byte count equals
  the source disk size;
- checks destination type, capacity, logical sector size, writability and
  safety; and
- revalidates destination identity and safety immediately before the first
  write.

After writing, it reads back exactly the source-sized byte range and compares
its size and SHA-256 with the bytes sent to the destination.

The image manifest records byte count and SHA-256, but is not digitally
signed. Integrity checking detects accidental or unauthorized changes to
the stored payload only when the expected manifest itself is trusted;
authenticity relies on repository protection and authenticated transport.

## Failure and recovery

A failed, cancelled or interrupted restore can leave the destination partly
or fully overwritten. Feclora does not roll back the write and does not
automatically resume it. Treat the target as untrusted, inspect the operation
journal and device identity, and repeat the restore only after a new explicit
review.

If the image is encrypted, a wrong identity or passphrase fails authentication
before the destination writer starts. Keep key material out of screenshots,
logs and documentation.

## Scope and limitations

- Whole-disk restore accepts raw disk-image artifacts only.
- The destination must be equal to or larger than the source; smaller-disk
  restore is a separate, incomplete workflow.
- Extra capacity is not automatically assigned to a partition or filesystem.
- A larger GPT target requires `sgdisk` for backup-header relocation and
  verification.
- Mockups and automated tests are not evidence of a successful restore on
  physical hardware. Maintainer release acceptance is tracked separately.
