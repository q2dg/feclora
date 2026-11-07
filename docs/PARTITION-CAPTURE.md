# Partition capture orchestration

`feclora.storage.capture` provides a read-only capture planner and process
runner for one partition.

## Tool selection

Known filesystem types map to the corresponding Partclone executable
(`partclone.extfs`, `partclone.ntfs`, `partclone.xfs`,
`partclone.btrfs`, `partclone.fat`, `partclone.exfat`, or
`partclone.f2fs`). The planner uses Partclone's documented clone mode,
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
Closing the progress dialog cancels the producer and prevents publication.
- Output is first written in a private staging directory beneath the repository.
  A non-zero producer exit prevents publication and staging data is discarded.
- A successful artifact is hard-linked into its final name; an existing name
  is never replaced.

## Scope

This is partition capture only. It does not yet capture partition tables,
whole-disk boot areas, filesystem consistency snapshots, or a complete
`ImageManifest`. It does not restore or clone to a target. Mounted/busy source checks and a final pre-capture revalidation are integrated.
The Local rescue TUI exposes capture with progress and cancellation. Partclone and dd command semantics are
based on the upstream Partclone usage documentation.
