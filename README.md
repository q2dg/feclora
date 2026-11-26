# Feclora

Feclora is a Fedora-based Live appliance for disk and partition imaging,
local and remote cloning, recovery and network deployment. Its production
operator interface is GTK4/libadwaita running natively on Wayland through
Weston DRM/KMS and Weston's kiosk shell on tty1; Cage is not used. The Live
image uses Fedora's official Weston, GTK4 and libadwaita packages, excludes
the Xorg and XWayland server packages, and forces GTK onto its native Wayland
backend. Optional unused X11 client modules in distribution RPMs are not
launched. See [the Fedora compatibility baseline](docs/FEDORA-45-COMPATIBILITY.md)
and [the build and acceptance runbook](docs/BUILD.md).

## What it does

- Capture whole disks (Feclora RAW or QCOW2) and supported partitions into
  manifest-backed images.
- Restore verified images to compatible disks or existing partitions, with
  explicit destructive confirmation.
- Clone local disks and partitions, or deploy to remote Clients using unicast
  and UDPcast multicast workflows.
- Use local, SSHFS, NFS, SMB/CIFS and S3-compatible image repositories.
- Boot the same Live environment through PXE; optional unattended restore uses
  validated answer files and has a narrower scope than interactive PXE.
- Capture Btrfs subvolume streams with full or incremental `btrfs send`,
  optional gzip/xz/zstd/lz4 compression and optional age encryption.
- Optionally encrypt supported image artifacts with age. Artifact integrity
  metadata uses SHA-256.

The Live session is ephemeral. Credentials, certificates and temporary
configuration are regenerated at boot; durable images belong in repositories
selected by the operator.

## Important scope limits

Filesystem and storage-layer support is conditional; consult the
[feature matrix](docs/FEATURE-MATRIX.md) before planning an operation.
Btrfs partition images remain limited to supported single-device filesystems.
The separate Btrfs subvolume stream workflow supports full and incremental
send/receive, but requires a filesystem-backed repository and an already
mounted destination Btrfs filesystem. It does not provision filesystems or
reconcile multi-device block layouts.

LVM logical volumes, raw LUKS2 containers and Stratis XFS filesystems have
separate source/target restrictions. Opened-LUKS-mapping imaging,
LUKS2-on-LV restore, coordinated multi-device Btrfs block imaging and
profile-aware storage-layer restore are not implemented.

## Documentation

Start with the [step-by-step operator guides](https://q2dg.github.io/feclora/GETTING-STARTED.html)
or browse the [complete guide index](https://q2dg.github.io/feclora/GUIDES.html).
Technical references:

- [Feature and compatibility matrix](docs/FEATURE-MATRIX.md)
- [Btrfs subvolume send/receive](docs/BTRFS-SUBVOLUME-SEND-RECEIVE.md)
- [Btrfs stream manifest contract](docs/BTRFS-SEND-MANIFEST.md)
- [Operational lifecycle runbook](docs/OPERATIONS.md)
- [Build and software validation](docs/BUILD.md)
- [Engineering roadmap](docs/ROADMAP.md)

## Build and test

Follow [docs/BUILD.md](docs/BUILD.md) for host prerequisites, static validation,
automated tests and build instructions.

## Built on

Fedora, Python, GTK4, PyGObject, Partclone, LVM2, cryptsetup, NetworkManager, UDPcast,
dnsmasq, iPXE, Caddy, age, zstd, LZ4, Lorax and QEMU/KVM.

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
