# Roadmap

This roadmap distinguishes code implementation, Cockpit integration and operator-owned validation. Feclora's primary interface is Cockpit; the old local `dialog` menu is no longer installed in the Live package.

The detailed, dependency-ordered implementation backlog and acceptance criteria live in [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md).

## Completed in source

- [x] Fedora 45 x86_64 Live-image build configuration and BIOS/UEFI boot assets.
- [x] Read-only block-device, partition and volume inventory.
- [x] Manifest-backed whole-disk and partition capture.
- [x] Verified whole-disk and partition restore engines.
- [x] Direct local disk-to-disk and partition-to-partition clone engines.
- [x] Compression, SHA-256 artifact verification, age encryption and minisign signing.
- [x] Source-safety checks, target geometry checks and explicit destructive confirmations.
- [x] Local managed CA/TLS identity bootstrap and Client CSR enrollment primitives.
- [x] Authenticated unicast deployment engine and UDPcast multicast restore engine.
- [x] PXE/iPXE boot-tree staging and transient dnsmasq/Caddy/firewalld service lifecycle.
- [x] Durable deployment journals, audit-state reconstruction from verified journals, and explicit interrupted-job reconciliation (reconstruction does not restore sessions or resume work).
- [x] Root-peer Unix IPC protocol integrated with the persistent systemd Server service and Cockpit lifecycle API.
- [x] Cockpit React/PatternFly package and privileged allowlisted backend.
- [x] Cockpit local operations wizard: disk/partition capture, restore and clone.
- [x] Cockpit storage/image inventory, operation journal summary and local image-security setup.
- [x] Cockpit Terminal remains available for system administration.
- [x] Initial Cockpit Server identity bootstrap from a currently assigned IPv4 address, including DHCP-server warning and managed trust-material initialization.
- [x] Cockpit PXE network-profile preflight and explicit activation/shutdown for ProxyDHCP and isolated DHCP, with persisted transient systemd units and reversible interface-scoped firewalld state.

## Remaining implementation work

See [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) for task-level checklists and acceptance criteria. Immediate priorities are remote disk-cloning integration, full PKI rotation, repository/credential lifecycle, durable local operations and accurate Server-side transfer progress. Storage growth and volume-aware workflows, PXE unattended orchestration, documentation and governance follow.

## Operator-owned validation (optional, not a software completion gate)

The project documents how an operator can build the Fedora 45 ISO and validate it in disposable virtual machines in [BUILD.md](BUILD.md). **Actually building the ISO is not required to complete the software backlog.** The documented procedure is sufficient unless the maintainer separately requests an ISO artifact.

Physical-disk destructive acceptance, BIOS/UEFI boot on target hardware, PXE operation on the deployment network and switch IGMP snooping/querier validation are also operator activities. They must not be reported as passed unless someone actually performs and records them.

Automated unit tests, static checks, shell validation, deterministic frontend installation/build, documentation checks and CI remain project responsibilities. Never claim these checks pass without running them or observing successful CI.
