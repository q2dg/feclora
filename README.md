# feclora

**Feclora** is a Fedora Server-based minimal Live appliance for disk imaging, cloning and recovery. It boots into a locked-down Firefox kiosk that opens the Feclora Cockpit application; it has no general-purpose desktop.

Project website: https://q2dg.github.io/feclora/

## Current implementation

- Fedora Linux 45, x86_64, with a Fedora Live image build pipeline for BIOS and UEFI.
- Cockpit web interface (React + PatternFly), launched in a Firefox kiosk.
- Local whole-disk and partition capture, restore and cloning.
- Capture and restore of eligible active LVM logical volumes.
- Image manifests, compression, SHA-256 integrity verification and optional age encryption. Manifests are not digitally signed.
- Storage and image inventories, safe-target checks, operation progress and local operation journals.
- Persistent Server/Client services, managed Server identity, Client enrollment and Server-authenticated TLS control and unicast transfer.
- UDPcast multicast restore and remote whole-disk / partition cloning.
- Network configuration and PXE/iPXE interactive Live boot.
- An initial unattended PXE workflow for NFS-backed whole-disk restore.

The Live session is ephemeral. Credentials, certificates and temporary configuration are regenerated at boot. Images and other durable artifacts are stored in repositories selected by the operator.

## Current limitations

- WebDAV and S3 repository integrations are not implemented. SSHFS, NFS and SMB/CIFS mounted repositories are supported in source.
- NVMe-oF host namespace management is not implemented.
- Unattended PXE currently covers the initial NFS whole-disk restore path, not a complete fleet workflow.
- Multi-device Btrfs imaging, snapshot-assisted storage capture and several advanced LUKS/LVM workflows are not supported.
- Automated tests and source validation do not prove ISO boot, firmware compatibility or physical-hardware acceptance.

See the [operator guides](docs/GUIDES.md), [feature matrix](docs/FEATURE-MATRIX.md), [build instructions](docs/BUILD.md) and [remaining work](docs/ROADMAP.md).

## Build and test

Follow [docs/BUILD.md](docs/BUILD.md) for build-host prerequisites, image build commands and BIOS/UEFI QEMU checks. ISO generation and physical-hardware acceptance are operator-run.

## Repository layout

```text
feclora/
├── .github/workflows/   # CI, tests and documentation deployment
├── build/               # Live image and frontend build scripts
├── docs/                # Operator, build and implementation documentation
├── kickstart/           # Fedora Live image configuration
├── packages/            # Runtime and build-host package manifests
├── src/feclora/         # Python backend and privileged operations
├── tests/               # Automated tests and acceptance procedures
├── webui/               # Cockpit React/PatternFly application
├── Makefile
└── README.md
```

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
