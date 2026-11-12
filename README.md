# feclora

**feclora** is an independent project to build a Fedora Server-based minimal Live appliance for disk imaging, cloning, and recovery. The target appliance boots into a locked-down Firefox kiosk opening the Feclora Cockpit application, without a general-purpose desktop environment.

Project website: [https://q2dg.github.io/feclora/](https://q2dg.github.io/feclora/).

It is not a fork of Clonezilla and does not depend on its repository, branches, or release process. Clonezilla may be used as a functional reference during requirements analysis; implementation and project history live here.

## Current source baseline and product target

- Fedora Linux 45, x86_64
- Fedora Live ISO build pipeline for BIOS and UEFI
- Cockpit and the Feclora Cockpit application
- Imaging, cloning, restoration, storage discovery and remote deployment foundations

**Runtime architecture now implemented in source:** Fedora Server product environment in a Live image, without a general-purpose desktop; Cockpit bound to loopback with socket activation; Cage + Firefox kiosk; locked administrator account with a loopback-only first-boot password assistant; and a locally generated Cockpit CA/certificate installed into Firefox's Linux certificate store. The Live filesystem is intentionally ephemeral: each boot starts a fresh Feclora session, and administrator credentials, local CA material and temporary configuration are regenerated. No Live-session persistence is required. Images, manifests and other durable artifacts belong in explicitly selected external repositories. BIOS/UEFI/physical kiosk acceptance remains open. See the [roadmap](docs/ROADMAP.md) and [implementation plan](docs/IMPLEMENTATION-PLAN.md).

## Design principles

1. **Independent implementation:** no upstream submodule, tracking branch, or automatic code synchronization.
2. **Fedora-native build:** use Fedora tooling and RPM packages; the Live image pipeline uses Fedora tooling, Kickstart, Lorax `livemedia-creator`, and QEMU.
3. **Modular capabilities:** keep image orchestration, storage discovery, filesystem support, networking, boot integration, and user interfaces separable.
4. **Safe operations:** make destructive actions explicit, validate source and target devices, and provide dry-run or confirmation paths where feasible.
5. **Reproducibility:** pin build inputs where practical and record package versions and build metadata.
6. **Tested compatibility:** document filesystem, partition-table, encryption, transport, firmware, and hardware coverage rather than assuming parity.
7. **Reuse mature system tools:** orchestrate Partclone, UDPcast, NetworkManager, OpenSSL, systemd, SSH/SFTP, NFS, SMB and davfs2 instead of reimplementing their capabilities. Integrate maintained transports such as BitTorrent as first-class distribution paths where they meet the product's security and acceptance requirements.

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
├── build/                  # Live ISO, kiosk/Cockpit frontend, host dependencies and validation
│   ├── build-iso.sh
│   ├── build-webui.sh
│   ├── install-host-deps.sh
│   ├── preflight.sh
│   └── validate.sh
├── docs/                   # Architecture, operator guides, feature matrix and ADRs
│   └── adr/                # Architecture Decision Records
├── kickstart/              # Fedora Server-based Live image Kickstart configuration
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
ProxyDHCP or isolated DHCP. PXE boot-tree staging and interactive Live boot are implemented. Cockpit can upload one declarative unattended JSON answer (including its repository URL); the Server validates it and publishes/revokes it through Caddy over HTTP together with an answer-specific iPXE handoff script. This answer workflow does not use per-Client identity, USB media, certificates or enrollment. Live downloads and schema-validates the answer, and the first NFS-backed whole-disk path uses the existing restore engine with WWN/serial revalidation and read-back verification. PXE can unlock passphrase-encrypted age artifacts through Live Cockpit; whole-disk capture can create symmetric age-encrypted images through Cockpit, while partition and logical-volume capture remain recipient-based; other repository adapters and hardware acceptance remain pending; the existing mTLS Remote jobs workflow remains separate. See [the PXE unattended design](docs/PXE-UNATTENDED.md).

Local long-running capture, restore, extraction and clone operations are
submitted through the privileged API to a root-owned systemd worker. Their
versioned definitions and hash-chained event journals under
`/var/lib/feclora/local-operations` survive browser, Cockpit/API and worker
process restarts during the current Live session. The default Live root is
ephemeral, so this queue/history is not retained across reboot; reboot
persistence is not required. A reboot during destructive I/O can leave a
partially written target with no surviving session journal, so inspect it
before reuse. Standardized phase/diagnostic telemetry, history export and live systemd acceptance
remain outstanding.

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
