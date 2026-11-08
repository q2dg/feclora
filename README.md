# feclora

**feclora** is an independent project to build a Fedora-based live system for disk imaging, cloning, and recovery, aiming for functional coverage comparable to Clonezilla.

It is not a fork of Clonezilla and does not depend on its repository, branches, or release process. Clonezilla may be used as a functional reference during requirements analysis; implementation and project history live here.

## Current build baseline

- Fedora Linux 45 (released 3 November 2026)
- x86_64
- Rescue-style bootable live ISO
- BIOS and UEFI boot support
- Native Fedora package management and system integration
- Imaging, cloning, restoration, and storage administration

The first milestone is a reproducible bootable live ISO with a verified core workflow. Broader functionality will be added in measured, testable increments.

## Design principles

1. **Independent implementation:** no upstream submodule, tracking branch, or automatic code synchronization.
2. **Fedora-native build:** use Fedora tooling and RPM packages; the initial image pipeline uses Lorax `livemedia-creator`, Kickstart, and QEMU.
3. **Modular capabilities:** keep image orchestration, storage discovery, filesystem support, networking, boot integration, and user interfaces separable.
4. **Safe operations:** make destructive actions explicit, validate source and target devices, and provide dry-run or confirmation paths where feasible.
5. **Reproducibility:** pin build inputs where practical and record package versions and build metadata.
6. **Tested compatibility:** document filesystem, partition-table, encryption, transport, firmware, and hardware coverage rather than assuming parity.

## Build and test

See [docs/BUILD.md](docs/BUILD.md) for Fedora build-host prerequisites, installer ISO verification, build commands, output inspection, and BIOS/UEFI QEMU acceptance procedure. The focused [VM smoke-test checklist](tests/VM-SMOKE-TEST.md) records boot and device-discovery checks.

Operational design notes:
- [Whole-disk restore and larger-target GPT repair](docs/WHOLE-DISK-RESTORE.md)
- [Mutually authenticated remote disk cloning](docs/REMOTE-DISK-CLONE.md)
- [Authenticated Server/Client deployment control, signed unicast transfer and multi-client multicast restore](docs/DEPLOYMENT-CONTROL.md)
- [Server and Client runtime configuration](docs/DEPLOYMENT-SETUP.md)
- [Signed, single-use unattended restore profiles](docs/RESTORE-PROFILES.md)
- [Certificate management policy and current limitations](docs/CERTIFICATE-MANAGEMENT.md)
- [Cockpit React/PatternFly web dashboard](webui/README.md)
- [Isolated BIOS/UEFI PXE VM lab](tests/vm/README.md)

## Repository layout

- `build/` — ISO build tooling and build-host setup
- `kickstart/` — Fedora installation and live-image configuration
- `packages/` — RPM package manifests
- `src/` — application and orchestration code
- `scripts/` — developer and operator utilities
- `tests/` — unit, integration, and VM smoke tests
- `docs/` — architecture, compatibility, and operational documentation

## Development status

Early implementation. The repository contains an initial Kickstart and a QEMU-backed `livemedia-creator` build script. The Python application payload and a React/PatternFly Cockpit package are wired into the Live-image pipeline; the Cockpit page currently provides a read-only dashboard for host/service status, image manifests, deployment journals and storage inventory. Local rescue supports manifest-backed whole-disk and partition capture/restore. Server mode has an opt-in dnsmasq/iPXE/Caddy PXE boot path, TLS 1.3 mTLS unicast save and disk/partition restore, and multi-client multicast disk/partition restore. Multicast accepts age-encrypted artifacts only; signed manifests bind the ciphertext and age authenticates it during decryption. Host-side multicast preflight checks interface flags, IPv4 address, kernel route and UDPcast tools, while switch IGMP configuration remains an operator check. The Server bootstraps a local CA and signs Client CSRs; Clients generate their own TLS and age keys, verify fingerprints, and can renew certificates using existing keys. Hash-chained journal replay and operator-driven restart reconciliation are implemented without automatic destructive resume. Full destructive workflows in Cockpit, per-client live multicast progress, server-side certificate expiry inventory and CRL validation remain pending. Multi-VM execution, ISO creation and BIOS/UEFI/PXE end-to-end acceptance have not been validated; no functional parity claim is made.

## Fedora baseline lifecycle

Fedora Linux 45 is the current project baseline. The Fedora Project announced its general availability on 3 November 2026. The ISO build scripts, Kickstart, package manifest, preflight checks, and build runbook are aligned to Fedora 45. Do not describe an older release as the current target.

Fedora has a short, regularly advancing release lifecycle. Before changing the project baseline again, update the release version consistently across the build scripts, Kickstart, package set, CI/build documentation, and acceptance tests; then build and boot-test the resulting ISO. A newer Fedora release must not become the baseline merely by changing a version string: validate package availability (especially storage and boot packages), installer behavior, BIOS/UEFI boot, and the rescue workflows first.

## License

License selection is pending. Individual components and dependencies may carry their own licenses; these will be documented before code is incorporated or redistributed.
