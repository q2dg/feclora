# Roadmap

This roadmap distinguishes code implementation, Cockpit integration and operator-owned validation. Feclora's primary interface is Cockpit; the old local `dialog` menu is no longer installed in the Live package.

The detailed, dependency-ordered implementation backlog and acceptance criteria live in [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md). Operator procedures are indexed in [GUIDES.md](GUIDES.md); only workflows implemented end to end are presented as available. Broader CA rotation and trust migration are deferred and are not offered as an available workflow.

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
- [x] Direct whole-disk Server-to-Client remote clone integrated into the persistent job lifecycle, existing mTLS control session, durable journals and Cockpit workflow.
- [x] PXE/iPXE boot-tree staging and transient dnsmasq/Caddy/firewalld service lifecycle.
- [x] Durable deployment journals, audit-state reconstruction from verified journals, and explicit interrupted-job reconciliation (reconstruction does not restore sessions or resume work).
- [x] Root-peer Unix IPC protocol integrated with the persistent systemd Server service and Cockpit lifecycle API.
- [x] Cockpit React/PatternFly package and privileged allowlisted backend.
- [x] Cockpit local operations wizard: disk/partition capture, restore and clone.
- [x] Cockpit storage/image inventory, operation journal summary and local image-security setup.
- [x] Cockpit Terminal remains available for system administration.
- [x] Initial Cockpit Server identity bootstrap from a currently assigned IPv4 address, including DHCP-server warning and managed trust-material initialization.
- [x] Cockpit PXE network-profile preflight and explicit activation/shutdown for ProxyDHCP and isolated DHCP, with persisted transient systemd units and reversible interface-scoped firewalld state.

## Project license

- [x] GNU General Public License v3.0 or later (`GPL-3.0-or-later`); see [LICENSE](../LICENSE).

## Remaining implementation work

See [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) for task-level checklists and acceptance criteria. Immediate priorities are repository credential/provider lifecycle, remote-clone disconnect/restart fault injection, consistent operation telemetry and Server-side artifact-transfer progress. Broader CA rotation and trust migration are explicitly deferred; the supported PKI scope remains managed CA bootstrap, enrollment/renewal, trust inventory/revocation, Server leaf renewal and Server TLS keypair rotation under the existing CA. CA backup does not provide CA rotation or compromise recovery. Durable local operations now have a root-owned systemd worker, persistent queue/journal, Cockpit status/history and boot-time interrupted-job recovery; live systemd and hardware acceptance remain outstanding. Storage growth and volume-aware workflows, PXE unattended orchestration, documentation and release governance follow. Remote-clone two-machine hardware and real network/storage-provider acceptance are operator-run procedures documented in [ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md). Automated fault-injection and recovery checks remain software test responsibilities.

## Operator-owned validation (optional, not a software completion gate)

The project documents how an operator can build the Fedora 45 ISO and validate it in disposable virtual machines in [BUILD.md](BUILD.md). **Actually building the ISO is not required to complete the software backlog.** The documented procedure is sufficient unless the maintainer separately requests an ISO artifact.

Physical-disk destructive acceptance, BIOS/UEFI boot on target hardware, PXE operation on the deployment network and switch IGMP snooping/querier validation are also operator activities. They must not be reported as passed unless someone actually performs and records them.

Automated unit tests, static checks, shell validation, deterministic frontend installation/build, documentation checks and CI remain project responsibilities. Never claim these checks pass without running them or observing successful CI.
