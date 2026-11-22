# Feclora

Feclora is a Fedora-based Live appliance for disk and partition imaging,
local and remote cloning, recovery and network deployment. Its keyboard-first
Textual interface runs directly on tty1 without a graphical desktop.

## What it does

- Capture whole disks (RAW or QCOW2) and supported partitions into manifest-backed images.
- Restore verified images to compatible disks or existing partitions, with explicit destructive confirmation.
- Clone local disks and partitions, or deploy to remote Clients using unicast and UDPcast multicast workflows.
- Use local, SSHFS, NFS, SMB/CIFS and S3-compatible image repositories.
- Boot the same Live environment through PXE; optional unattended restore uses validated answer files and has a narrower scope than interactive PXE.
- Optionally encrypt image artifacts with age. Image integrity metadata uses SHA-256.

The Live session is ephemeral. Credentials, certificates and temporary
configuration are regenerated at boot; durable images belong in repositories
selected by the operator.

## Important scope limits

Feclora supports ext2/3/4, XFS, NTFS, FAT12/16/32, exFAT and F2FS, plus single-device
Btrfs partitions, subject to the feature matrix. LVM logical volumes and raw
LUKS2 containers have documented restrictions. Stratis is inventoried but is
not a fully supported imaging target. Coordinated multi-device/snapshot Btrfs
imaging, opened-LUKS-mapping imaging and LUKS2-on-LV restore are not implemented.
The recovery-ISO builder and guarded Live boot-time restore dispatch are
implemented; BIOS/UEFI boot and destructive restore acceptance remain operator
responsibilities.

Source integration and automated tests do not establish release acceptance.
The repository maintainer owns ISO generation and BIOS/UEFI, physical-hardware,
live-provider and real-network acceptance.

## Documentation

Start with the [step-by-step operator guides](https://q2dg.github.io/feclora/GETTING-STARTED.html)
or browse the [complete guide index](https://q2dg.github.io/feclora/GUIDES.html).
Technical references:

- [Feature and compatibility matrix](docs/FEATURE-MATRIX.md)
- [Operational lifecycle runbook](docs/OPERATIONS.md)
- [Build and software validation](docs/BUILD.md)
- [Maintainer acceptance checklist](docs/MAINTAINER-ACCEPTANCE.md)
- [Engineering roadmap](docs/ROADMAP.md)

## Build and test

Follow [docs/BUILD.md](docs/BUILD.md) for host prerequisites, static validation,
automated tests, ISO build instructions and disposable QEMU checks. ISO
generation and hardware/network acceptance are maintainer-run activities.

## Built on

Fedora, Python, Textual, Partclone, LVM2, cryptsetup, NetworkManager, UDPcast,
dnsmasq, iPXE, Caddy, age, zstd, LZ4, Lorax and QEMU/KVM.

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
