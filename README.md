# feclora

**feclora** is an independent project to build a Fedora-based live system for disk imaging, cloning, and recovery, with a Cockpit-based web interface for local imaging, restoration, cloning and remote deployment management.

Project website: [https://q2dg.github.io/feclora/](https://q2dg.github.io/feclora/).

It is not a fork of Clonezilla and does not depend on its repository, branches, or release process. Clonezilla may be used as a functional reference during requirements analysis; implementation and project history live here.

## Current build baseline

- Fedora Linux 45 (released 3 November 2026)
- x86_64
- Rescue-style bootable live ISO
- BIOS and UEFI boot support
- Native Fedora package management and system integration
- Imaging, cloning, restoration, and storage administration from Cockpit
- Cockpit Terminal for system-level diagnostics and advanced administration

The project is organized around a Cockpit-first Live environment. The remaining implementation and integration work is tracked in [the roadmap](docs/ROADMAP.md).

## Design principles

1. **Independent implementation:** no upstream submodule, tracking branch, or automatic code synchronization.
2. **Fedora-native build:** use Fedora tooling and RPM packages; the initial image pipeline uses Lorax `livemedia-creator`, Kickstart, and QEMU.
3. **Modular capabilities:** keep image orchestration, storage discovery, filesystem support, networking, boot integration, and user interfaces separable.
4. **Safe operations:** make destructive actions explicit, validate source and target devices, and provide dry-run or confirmation paths where feasible.
5. **Reproducibility:** pin build inputs where practical and record package versions and build metadata.
6. **Tested compatibility:** document filesystem, partition-table, encryption, transport, firmware, and hardware coverage rather than assuming parity.
7. **Reuse mature system tools:** orchestrate Partclone, UDPcast, NetworkManager, OpenSSL, systemd, SSH/SFTP, NFS, SMB and davfs2 instead of reimplementing their capabilities. Add maintained optional transports such as BitTorrent only where they solve a concrete distribution need.

## Build and test

See [docs/BUILD.md](docs/BUILD.md) for Fedora build-host prerequisites, installer ISO verification, build commands, output inspection, and BIOS/UEFI QEMU acceptance procedure. The focused [VM smoke-test checklist](tests/VM-SMOKE-TEST.md) records boot and device-discovery checks.

Operational design notes:
- [Tool reuse, repository types and optional transports](docs/TOOLING-AND-TRANSPORTS.md)
- [Optional image-security packages (`age` and `minisign`)](packages/optional-image-security.txt)
- [Durable local storage operations and crash recovery](docs/DURABLE-LOCAL-OPERATIONS.md)
- [Whole-disk restore and larger-target GPT repair](docs/WHOLE-DISK-RESTORE.md)
- [Mutually authenticated remote disk cloning](docs/REMOTE-DISK-CLONE.md)
- [Authenticated Server/Client deployment control, signed unicast transfer and multi-client multicast restore](docs/DEPLOYMENT-CONTROL.md)
- [Server and Client runtime configuration](docs/DEPLOYMENT-SETUP.md)
- [Signed, single-use unattended restore profiles](docs/RESTORE-PROFILES.md)
- [Certificate management policy and current limitations](docs/CERTIFICATE-MANAGEMENT.md)
- [Cockpit React/PatternFly web dashboard](webui/README.md)
- [Cockpit activation, access and security boundary](docs/COCKPIT.md)
- [Isolated BIOS/UEFI PXE VM lab](tests/vm/README.md)

## Repository layout

Contribution and engineering safety expectations are documented in [CONTRIBUTING.md](CONTRIBUTING.md). Feclora is licensed under the GNU General Public License v3.0 or (at your option) any later version. See [LICENSE](LICENSE) for the complete license text.

The repository is organized by runtime responsibility rather than by UI:

```text
feclora/
├── .github/
│   └── workflows/          # CI, Python tests and GitHub Pages deployment
├── build/                  # ISO, Cockpit frontend, host dependencies and validation
│   ├── build-iso.sh
│   ├── build-webui.sh
│   ├── install-host-deps.sh
│   ├── preflight.sh
│   └── validate.sh
├── docs/                   # Architecture, operator guides, feature matrix and ADRs
│   └── adr/                # Architecture Decision Records
├── kickstart/              # Fedora Live image Kickstart configuration
├── packages/               # Runtime and build-host RPM package manifests
├── src/feclora/             # Python application and privileged operation backend
│   ├── data/               # systemd units and restore-profile environment
│   ├── deployment/         # Server/Client, enrollment, PKI, jobs and journals
│   ├── network/            # PXE/iPXE, TLS, UDPcast and remote-clone transport
│   ├── storage/            # inventory, capture, restore, clone and image security
│   ├── ui/                 # legacy console UI code (not the supported Live interface)
│   └── webapi.py           # allowlisted Cockpit-to-Python API
├── tests/                  # Python unit/integration tests and VM acceptance assets
│   └── vm/                 # PXE virtual-machine matrix and instructions
├── webui/                  # Cockpit React/PatternFly application
│   ├── public/             # Cockpit application metadata
│   └── src/                # React UI and API client
├── Makefile                # Developer entry points
└── README.md
```

The main implementation boundaries are:

- **`webui/`** is the browser application. It does not execute privileged
  commands directly.
- **`src/feclora/webapi.py`** is the narrow, allowlisted privileged API used
  by Cockpit; storage and deployment logic remains in independent Python
  modules.
- **`src/feclora/storage/`** contains local storage engines and image formats.
- **`src/feclora/deployment/`** contains remote deployment orchestration,
  identities, enrollment and job state.
- **`src/feclora/network/`** contains network discovery, PXE services and
  transport protocols.
- **`build/`**, **`kickstart/`** and **`packages/`** define how the Live
  environment is assembled.
- **`tests/`** contains automated tests plus VM/laboratory acceptance
  instructions; tests that require a built ISO or destructive hardware
  operations are intentionally operator-run.
- **`docs/`** is the source for the GitHub Pages documentation site.

## Development status

Feclora's primary operator interface is Cockpit (React + PatternFly); the old
`dialog` local-rescue menu is no longer part of the Live package. The current
web application provides local whole-disk and partition image capture,
restoration, whole-disk and partition cloning, device and image inventories,
operation journals, streamed progress, and optional artifact encryption/signing integrations. `age` encryption and `minisign` signatures are optional capabilities, not prerequisites for local imaging or Feclora installation.

The underlying Python storage engines include safety checks, manifest-backed
artifact publication, compression, integrity verification, and restore
preflight. The remote deployment stack includes persistent Server/Client
services, mTLS enrollment and authorization, mTLS-authenticated unicast image transfer with optional minisign signatures,
UDPcast multicast restore, and direct whole-disk remote cloning. Cockpit
exposes Server/Client lifecycle and job workflows, per-client status, initial
Server identity bootstrap, and PXE network-profile preflight/activation for
ProxyDHCP or isolated DHCP. The PXE workflow still has network-configuration,
diagnostics and unattended-profile gaps tracked in the implementation plan.

Local long-running capture, restore, extraction and clone operations are
submitted through the privileged API to a root-owned systemd worker. Their
versioned definitions and hash-chained event journals persist under
`/var/lib/feclora/local-operations`; Cockpit displays durable status, progress
and history. Boot recovery marks unfinished jobs interrupted and never
replays destructive I/O. Phase/throughput telemetry, export and live systemd
acceptance remain outstanding.

The source tree and CI checks do not establish ISO boot or physical-device
acceptance. Local storage and Cockpit workflows still require validation on a
live system with disposable devices. ISO generation, BIOS/UEFI boot and
laboratory restore/deployment acceptance are intentionally left to the
operator.

## Fedora baseline lifecycle

Fedora Linux 45 is the current project baseline. The Fedora Project announced its general availability on 3 November 2026. The ISO build scripts, Kickstart, package manifest, preflight checks, and build runbook are aligned to Fedora 45. Do not describe an older release as the current target.

Fedora has a short, regularly advancing release lifecycle. Before changing the project baseline again, update the release version consistently across the build scripts, Kickstart, package set, CI/build documentation, and acceptance tests; then build and boot-test the resulting ISO. A newer Fedora release must not become the baseline merely by changing a version string: validate package availability (especially storage and boot packages), installer behavior, BIOS/UEFI boot, and the rescue workflows first.

## License

Feclora is licensed under the **GNU General Public License v3.0 or (at your option) any later version** (`GPL-3.0-or-later`). The complete license text is available in [LICENSE](LICENSE). Individual components and dependencies may carry their own licenses; their applicable notices and terms must be respected when they are incorporated or redistributed.
