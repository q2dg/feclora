# Manifest-backed partition capture

`feclora.storage.partition_image_capture.capture_partition_image` wraps the
read-only Partclone/dd capture engine in a versioned partition manifest.

The operation records source partition size, logical sector size, filesystem
metadata when recognized, artifact format, compression, stored byte count and
SHA-256. Raw dd capture is rejected unless its output byte count exactly
matches the source partition geometry. Partclone captures record their
filesystem so the matching restore executable can be selected later.

The data artifact is staged first; the manifest is published last as the image
set commit marker. Existing names are never overwritten. A failed transaction
rolls back names published by that transaction. An orphan payload without a
manifest is not considered a valid image set.

Supported compression is none, gzip and xz. The capture engine remains
read-only and uses generic Partclone or dd executables; it does not use any
Clonezilla `ocs-*` or DRBL component.
