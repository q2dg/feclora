# Image manifest schema v1

Feclora publishes an image as one or more artifact files plus a validated
`manifest.json`. The manifest describes the captured source and stored bytes.
It is not an executable restore plan and never authorizes a target write.

## Image types and current capture support

| Manifest image type | Meaning | Capture status | Restore status |
|---|---|---|---|
| `disk` | Complete block-device image plus partition-table metadata | Implemented in local GTK workflow as compressed/encrypted RAW or QCOW2 | Implemented for an existing whole-disk target; QCOW2 is verified and converted to private RAW staging before writing |
| `partition` | One existing partition, captured with Partclone when supported or raw bytes otherwise | Implemented in local GTK workflow; requires current storage inventory | Implemented for an existing partition target |
| `logical_volume` | One active LVM logical volume in a healthy VG | Implemented in local GTK workflow for uniquely identified, non-hidden, non-snapshot LVs | Implemented into an existing active, unmounted linear or thin LV after topology, identity, capacity and sector-size preflight; no LVM objects are created or resized |
| `stratis_filesystem` | Filesystem data from one existing Stratis XFS filesystem | Implemented in local GTK workflow; requires complete Stratis metadata and `partclone.xfs` | Implemented into a distinct, pre-created, active and unmounted Stratis XFS filesystem; no pool/filesystem provisioning or resize |

These are **image source types/layers**, not repository types. A repository is
the explicitly selected local or remote destination holding the image files.
SSHFS, NFS and SMB/CIFS are remote filesystem transports; S3 is an object-storage transport;
LVM, LUKS2 and Btrfs describe the source storage being imaged.

## Storage-layer scope

The optional `storage` object records the planner's view of the source layer,
byte scope and dependencies. It is provenance, not a command to activate,
unlock, mount, snapshot, format or modify storage.

- **LVM logical volume:** the current capture path accepts an active LV whose
  path and kernel major/minor identity resolve uniquely, whose size is known,
  and whose VG/PV topology is healthy. Hidden and snapshot LVs are excluded.
  The resulting `logical_volume` image is a byte image of that LV, not a
  self-contained backup of the VG, PV metadata or all VG members. Restore is
  implemented only into an already existing active, unmounted linear or thin
  LV. Preflight revalidates the target's VG/PV health, kernel identity,
  capacity, logical sector size, mount state and snapshot relationships;
  thin-pool health and estimated free capacity are checked as well. The
  capacity estimate is not a reservation against concurrent LVM activity.
  Restore writes the image bytes into the LV and verifies the result (raw
  read-back or a filesystem-specific Partclone check). It does not create,
  activate, resize or otherwise provision LVM objects, and it does not back up
  VG/PV metadata or dependent LVs.
- **LUKS2 container:** partition capture can record raw encrypted-container
  bytes only when `cryptsetup` verifies a version-2 header and UUID. The
  captured bytes include the LUKS2 header/keyslots; passphrases and recovery
  keys are never captured. LUKS1 and unknown/unverified headers fail closed
  for this layer-aware path.
- **Opened LUKS mapping:** inventory and planning can describe an active
  mapping, but a dedicated mapping-image capture workflow is not exposed.
  Do not interpret mapping provenance as proof that such a capture is
  available.
- **Btrfs:** supported single-device Btrfs partitions can be captured as
  filesystem/block-device images. The manifest records the filesystem UUID
  and verified device count; restore requires a single-device count and one
  matching complete-filesystem dependency before any writer starts. Multi-device
  filesystems are rejected by partition capture and restore rather than being
  flattened onto one target. Read-only inventory now records Data/Metadata/
  System allocation profiles (for example `single` or `DUP`) for filesystems
  that are already mounted; it does not mount sources or alter the filesystem.
  Profile inventory is observational and is not yet a profile-conversion or
  multi-device restore engine. There is no coordinated multi-device capture,
  snapshot-assisted consistency workflow or separate subvolume image.
  Subvolume UUIDs, when present, are provenance only.
- **Stratis XFS filesystem:** a dedicated local workflow captures the
  filesystem data from an existing active, unmounted Stratis XFS filesystem.
  Capture requires complete pool/filesystem names and UUIDs, matching logical
  and block-device capacities, and `partclone.xfs`; raw fallback is disabled.
  The manifest records pool/filesystem provenance and one external
  `stratis_pool` dependency. Restore is limited to a distinct, pre-created,
  active and unmounted Stratis XFS filesystem. It revalidates pool and
  filesystem identity, kernel device identity, logical capacity and sector
  size, and performs an XFS read-only consistency check. It does not create
  pools/filesystems, resize the target, capture pool metadata or image backing
  devices. Physical pool free space is not treated as filesystem logical
  capacity. Live Stratis media acceptance remains an operator task.

A raw LUKS2 partition image can be restored through the ordinary partition
restore path as bytes to an existing compatible partition. That operation
does not provision encryption, unlock the result, or manage keys. A
layer-aware Btrfs restore workflow remains unimplemented.

## Schema fields and artifact roles

The validator supports `image_type` values `disk`, `partition`,
`logical_volume` and `stratis_filesystem`. Source capacity and logical sector
size are recorded; logical-volume and Stratis filesystem manifests use
`partition_table: "none"` and require storage provenance.

Artifact roles include:

- `partition-table`: GTK partition-table metadata (not a block image).
- `disk-metadata`: descriptive source metadata.
- `boot-area`: raw boot-area bytes where explicitly captured.
- `disk-image`: raw whole-disk stream or QCOW2 virtual-disk container.
- `partition-image`: Partclone stream or raw partition byte stream.
- `logical-volume-image`: Partclone stream or raw LV byte stream; valid only
  for `logical_volume` manifests and requires storage metadata.
- `stratis-filesystem-image`: Partclone XFS stream; valid only for
  `stratis_filesystem` manifests and requires Stratis pool/filesystem metadata.

For whole-disk images, the `disk-image` format may be `raw` or `qcow2`.
QCOW2 artifacts must be uncompressed and unencrypted; the manifest's
`source_size_bytes` is the QCOW2 virtual capacity, not the stored file length.
Restore verifies the stored digest, rejects backing or external data-file
dependencies before structural checking, checks the virtual capacity, and
converts to a private RAW staging file before using the normal whole-disk
writer. The temporary filesystem needs free space for the stored QCOW2 file,
the full RAW virtual capacity and a small safety margin. No guest driver,
initramfs or firmware repair is performed.

Each artifact records a safe basename, role, encoding, compression,
encryption, stored byte length and SHA-256 digest. Partition-image and
logical-volume-image artifacts may also record a recognized filesystem type.
The LV manifest requires exactly one `logical-volume-image` artifact and no
other artifact role.

The optional `storage` object has its own schema version and validates
capture scope, source layer, supported LUKS/LVM/Btrfs identifiers (including
the positive Btrfs device count) and a restricted dependency list. Unknown fields, invalid types, incompatible
scopes and unsupported dependency kinds are rejected. Legacy disk/partition
manifests without `storage` remain readable; legacy Btrfs partition images without
single-device topology provenance are intentionally refused by the restore preflight.

## Integrity and encryption

SHA-256 covers the exact stored artifact bytes. Compression is applied before
optional age encryption. For an age-encrypted artifact, restore verifies the
ciphertext size/digest first, then authenticates/decrypts into private staging
before decompression or target writes.

SHA-256 digests in the manifest detect artifact corruption relative to the recorded metadata. They do not authenticate the publisher. The manifest is repository metadata protected by transport authentication and repository access controls.

Repository publication uses the manifest as its visibility marker. This is
not a general crash-recovery transaction across arbitrary filesystems. Do not
treat orphaned artifacts without a manifest as a complete image set.
