# Image artifact writer

`feclora.storage.artifact_writer.write_artifact` accepts a readable binary
stream and stores it as a new artifact in an existing repository directory.
It does not discover disks, invoke `partclone`/`dd`, or write to block devices.

## Guarantees

- Safe basename validation; no caller-supplied subdirectory paths.
- Destination directory must exist and must not be a symlink.
- Temporary file is created in that directory with mode 0600 and exclusive
  creation; existing artifact names are never overwritten.
- Data is streamed in bounded chunks. The stored bytes are hashed with SHA-256
  and counted, including compression framing.
- The temporary file and containing directory are fsynced; a hard-link
  publishes the complete file atomically without replacing an existing name.
- Temporary files are removed on errors.

## Compression support

Version one supports `none`, `gzip`, and `xz` using Python's standard
library. The manifest schema also recognizes zstd and lz4, but this writer
rejects those until a separately tested streaming adapter is implemented.
This avoids silently substituting a different codec.

## Boundary and remaining work

The caller owns the input stream and must check the imaging process exit status
before accepting the artifact as a valid capture. A failed producer can emit
partial bytes before exiting; this writer cannot infer producer success.
The caller must also validate role/format/partition metadata by constructing
an `ImageManifest` before publishing a complete image set. Repository-level
manifest commit/rollback and device capture orchestration are not implemented.


## External codecs

The writer also supports zstd (levels 1-19) and lz4 (levels 1-12) through the
system `zstd` and `lz4` executables. Input is streamed through stdin, output is
written directly to the private staging file, and the process exit status is
checked before publication. SHA-256 and stored size are computed from the
resulting compressed bytes. Restore uses the matching CLI decompressor with
streamed stdout; it checks the decompressor exit status before allowing the
restore to proceed. Fedora Live installs the `zstd` and `lz4` packages.
