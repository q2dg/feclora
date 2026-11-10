# Whole-disk restore

feclora implements whole-disk restore in
`feclora.storage.disk_restore.restore_disk`.

It accepts a schema-v1 disk manifest and exactly one raw `disk-image`
artifact. The destination may be equal to or larger than the source image; a
smaller destination is rejected. The logical sector size must match.

Before starting the writer it:

1. requires the caller's exact confirmation string, `ERASE /dev/DEVICE`;
2. validates the manifest and requires a whole-disk image;
3. checks the target is a writable whole disk, at least as large as the source,
   with the same logical sector size;
4. rejects mounted target trees and disks backing the running Live root;
5. opens the artifact without following symlinks and verifies its stored byte
   count and SHA-256 against the manifest;
6. if a detached signature is present, verifies it with an independently trusted minisign public key; a signed image cannot be restored without successful verification. It also fully decompresses
   the artifact before touching the target;
7. repeats target identity and safety checks immediately before starting
   `dd`;
8. hashes the bytes sent to the writer, then reads the restored source-sized
   byte range back from the destination with `dd` and compares byte count and
   SHA-256;
9. when the destination is larger and the source partition table is GPT,
   relocates the backup GPT header to the physical end of the destination
   with `sgdisk -e` and validates the table with `sgdisk -v`.

The additional destination capacity is left unallocated. feclora does not
silently resize partitions or filesystems during a raw whole-disk restore.
MBR and unpartitioned images retain their original layout; GPT repair is only
performed after the source-sized byte range has passed read-back verification.

The writer uses generic `dd of=TARGET bs=4M conv=fsync status=none`. Raw,
gzip, xz, zstd and lz4 disk artifacts are supported. The Cockpit operation displays write
progress and supports cancellation; a cancellation can leave a partially
overwritten target. Read-back verification runs after a successful write.
Capture/restore operation events are persisted in the append-only operation
journal.

**Destructive boundary:** once `dd` starts, a hardware or power failure can
leave the target partially overwritten. SHA-256 detects accidental corruption;
it does not authenticate who created the manifest. A configured signature verifier (currently minisign)
establishes authenticity only when the public key is independently trusted.

Tests use mocked device I/O. No VM or hardware restore has been validated.
Never test against a disk containing needed data.


Age decryption staging uses the local system temporary filesystem, not the source repository, so a read-only remote repository can be used. Ensure the local temporary filesystem has enough free space for the decrypted artifact. `age` encryption and `minisign` signatures are optional integrations. A missing
age executable must not block restoration of unencrypted images. A missing
minisign executable must not block unsigned/local baseline restores; if an
image carries a signature, the verifier and an independently trusted public
key are mandatory and failure blocks restoration before the first write. SHA-256 alone is not publisher authentication.
