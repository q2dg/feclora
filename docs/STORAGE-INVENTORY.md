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
