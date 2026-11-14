# Read-only storage inventory

The first storage component is an inspection-only inventory. It invokes
`lsblk --json --bytes --paths` and emits a stable JSON document containing
block-device and filesystem metadata, including nested partitions.

## Run

From the repository root:

```bash
PYTHONPATH=src python3 -m feclora.storage.inventory --json
```

The command does not require root for ordinary device metadata. Access to some
optional fields may depend on system permissions and the installed util-linux
version. Missing optional columns are represented as JSON null values or empty
lists.

## Safety boundary

This component only invokes `lsblk` in query mode. It does not mount or
unmount filesystems, probe by writing signatures, change partition tables,
activate/deactivate volumes, or open devices for writing. In particular, it
does not call `wipefs`, `parted`, `mkfs`, `mount`, or `dd`.

The inventory is observational, not a guarantee that a device is healthy or
safe as an imaging source/target. The future imaging workflow must independently
validate device identity and enforce destructive-operation safeguards.

## Tests

Run the hardware-independent unit tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Tests use mocked `lsblk` output; they do not access or modify real block devices.

## LUKS2 metadata discovery

LUKS inventory uses `cryptsetup luksUUID` and
`cryptsetup luksDump --dump-json-metadata` in read-only mode. A container is
reported as verified LUKS2 only when the JSON has a canonical UUID, valid
encryption segments, consistent cipher and sector-size settings, and
well-formed keyslot/token/config sections. The UUID returned by the separate
`luksUUID` query must match the JSON UUID. Malformed or disagreeing metadata
is reported as an inspection error and is not passed to the layer-aware
capture planner.

Only a summary is retained: UUID, cipher, sector size, counts and metadata
size. Keyslot and token payloads, passphrases and recovery material are never
copied into the inventory. LUKS1 is identified separately and is not accepted
by the LUKS2 layer-aware workflow.

## Btrfs metadata discovery

Btrfs discovery first uses `btrfs filesystem show --raw --all-devices` to
identify filesystem UUIDs and every detected member device. The inventory
rejects non-canonical or duplicate filesystem UUIDs, incomplete member counts,
duplicate/non-positive device IDs, duplicate paths, zero-sized devices and
missing/non-`/dev` member paths instead of silently accepting a partial set.
For each complete device set, Feclora runs the read-only
`btrfs inspect-internal dump-tree --noscan -t root` against the supplied
members. This reads the on-disk root tree without mounting the filesystem and
records current subvolume IDs, generations, used bytes, read-only flags,
subvolume UUIDs, snapshot parent UUIDs, received UUIDs and ROOT_BACKREF parent
relationships. Subvolume paths are resolved only when the parent chain and
names are present and unambiguous.

The unmounted chunk-tree scan also records DATA/METADATA/SYSTEM chunk
types, allocation profiles, logical chunk lengths, stripe counts, and the
device IDs/offsets backing each chunk. Per-profile totals represent logical
allocated bytes and the union of member device IDs; unmounted used-byte
accounting is not inferred (`used_bytes` remains null). The mounted
`btrfs filesystem df` view continues to provide used-byte observations and
GlobalReserve information. The root/chunk tree queries do not read file data;
the root tree does expose subvolume names used to resolve paths.

Coordinated snapshot-consistent capture and multi-device/profile imaging
remain pending. Incomplete or ambiguous device sets are not flattened into
standalone partition images.

The read-only capture planner consumes these observations before imaging. It
requires every Btrfs member device and complete chunk-to-device stripe mapping,
rejects unknown allocation profiles, and blocks a filesystem found mounted
through either block-device mountpoints or Btrfs mount inventory. It does not
create snapshots: capture is only considered when the filesystem is cleanly
unmounted and remains quiescent. Snapshot-assisted capture and coordinated
multi-device imaging/restoration remain unimplemented.
