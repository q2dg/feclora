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

## Btrfs metadata discovery

Btrfs discovery first uses `btrfs filesystem show --raw --all-devices` to
identify filesystem UUIDs and every detected member device. For each complete
device set, Feclora runs the read-only
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
