# Whole-disk restore

feclora now has an initial whole-disk restore primitive in
`feclora.storage.disk_restore.restore_disk`.

It accepts a schema-v1 disk manifest and exactly one raw `disk-image`
artifact. Before starting the writer it:

1. requires the caller's exact confirmation string, `ERASE /dev/DEVICE`;
2. validates the manifest and requires a whole-disk image;
3. checks the target is a writable whole disk, at least as large as the source, with the same logical sector size;
4. rejects mounted target trees and disks backing the running Live root;
5. opens the artifact without following symlinks and verifies its stored byte
   count and SHA-256 against the manifest;
6. fully decompresses the artifact once before touching the target and checks
   the decoded byte count against the manifest;
7. repeats target identity and safety checks immediately before starting
   `dd`;
8. hashes the bytes sent to the writer, then reads the restored byte range
   back from the destination with `dd` and compares the byte count and SHA-256.

The writer uses generic `dd of=TARGET bs=4M conv=fsync status=none`. Raw,
gzip and xz disk artifacts are supported. zstd/lz4, partition-image restore,
partition-table reconstruction, crash recovery and persistent operation logs
are not implemented. The TUI displays write progress and can cancel the writer;
a cancellation can leave a partially overwritten target. Read-back verification
runs after a successful write.

**Destructive boundary:** once `dd` starts, a hardware or power failure can
leave the target partially overwritten. SHA-256 here detects accidental
artifact corruption; it does not authenticate who created the manifest.
The Local rescue TUI invokes this primitive after exact typed confirmation. The TUI shows live progress and supports cancellation. Tests are mocked; no VM or hardware restore has been validated. Never test against a disk containing needed data.
