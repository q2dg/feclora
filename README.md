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
- [Cockpit activation, access and security boundary](docs/COCKPIT.md)
- [Isolated BIOS/UEFI PXE VM lab](tests/vm/README.md)

## Repository layout

Contribution and engineering safety expectations are documented in [CONTRIBUTING.md](CONTRIBUTING.md). The project license has not yet been selected; see the roadmap before assuming reuse or redistribution rights.\n\nThe repository is organized by runtime responsibility rather than by UI:

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
operation journals, streamed progress, and optional age encryption plus
minisign signatures using locally managed keys.

The underlying Python storage engines include safety checks, manifest-backed
artifact publication, compression, integrity verification, and restore
preflight. The remote deployment engines include mTLS enrollment, signed
unicast image transfer, PXE/iPXE boot infrastructure and UDPcast multicast
restore. Cockpit now provides initial Server identity bootstrap and PXE network-profile
preflight for ProxyDHCP or isolated DHCP. It validates daemon configuration
without starting services. Complete Server/Client network activation,
enrollment, job lifecycle and per-client live progress still need to be
integrated. Local storage flows and
the new Cockpit frontend have not yet been exercised against a built ISO or
physical disks; CI status must be checked before claiming automated test
success. ISO generation, BIOS/UEFI boot and laboratory restore/deployment
acceptance are intentionally left to the operator.

## Fedora baseline lifecycle

Fedora Linux 45 is the current project baseline. The Fedora Project announced its general availability on 3 November 2026. The ISO build scripts, Kickstart, package manifest, preflight checks, and build runbook are aligned to Fedora 45. Do not describe an older release as the current target.

Fedora has a short, regularly advancing release lifecycle. Before changing the project baseline again, update the release version consistently across the build scripts, Kickstart, package set, CI/build documentation, and acceptance tests; then build and boot-test the resulting ISO. A newer Fedora release must not become the baseline merely by changing a version string: validate package availability (especially storage and boot packages), installer behavior, BIOS/UEFI boot, and the rescue workflows first.

## License

License selection is pending. Individual components and dependencies may carry their own licenses; these will be documented before code is incorporated or redistributed.
