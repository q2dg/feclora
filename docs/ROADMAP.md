# Roadmap

This roadmap distinguishes code implementation, Cockpit integration and operator-owned validation. Feclora is a Live appliance based on a minimal Fedora Server userspace, without a general-purpose desktop. Its local display is intended to run Firefox in a Cage kiosk session, fixed to Cockpit and the Feclora application; the old local `dialog` menu is not part of the supported interface.

The detailed, dependency-ordered implementation backlog and acceptance criteria live in [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md). Operator procedures are indexed in [GUIDES.md](GUIDES.md); only workflows implemented end to end are presented as available. Broader CA rotation and trust migration are deferred and are not offered as an available workflow.


## Maintainer's end-user target

The release target is a bootable Fedora Server minimal Live kiosk appliance, with automatic Cockpit socket activation and Firefox as its fixed local browser, covering six end-to-end workflows: local disk/partition cloning; remote disk/partition cloning with DHCP/static networking; image capture to SSHFS, SFTP, NFS, SMB/CIFS and WebDAV (once provider-specific credential and write capabilities are complete); restore from those repositories to one local target; multi-Client restore with manual Feclora or PXE boot; and unattended multi-Client restore. Measurable acceptance gates, security requirements and guide requirements are maintained in [USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.md).

BitTorrent is a first-class peer-to-peer distribution transport for immutable, verified image artifacts, with the same implementation priority as SSHFS, SFTP, NFS, SMB/CIFS and WebDAV. It is not a general writable repository. `age` and `minisign` are optional integrations and must not be mandatory installation or release requirements. Their absence must not prevent ordinary local imaging or deployment where another configured trust/integrity mechanism is used.

The present implementation is a foundation, not completion of that target. In particular, SSHFS with SFTP, PXE service lifecycle with PXE job handoff, or signed-profile primitives with unattended fleet deployment. Only advertise a workflow as available when its Cockpit path, backend/runtime, authorization, error handling, tests and published operator guide are complete.

## Runtime architecture and immediate work

The image remains **Live**: it boots from removable media without requiring
installation to disk. Its operating-system base is a minimal Fedora Server
userspace, not Fedora Workstation and not a full graphical desktop. Cockpit is
the administration surface; Firefox runs in kiosk mode under a minimal
Wayland compositor (Cage). The browser opens the local Cockpit endpoint and
the Feclora Cockpit application.

The source now implements the core kiosk path: Fedora Server product environment, Cage + Firefox, a separate unprivileged kiosk account, locked administrator account with loopback-only first-boot password setup, a locally generated trusted Cockpit certificate, Firefox origin allowlisting, and systemd supervision. BIOS/UEFI boot, certificate behavior in the packaged Firefox build, keyboard/TTY escape resistance, and physical display/input behavior remain operator acceptance tasks. Cockpit authentication and backend authorization remain mandatory.

## Completed in source

- [x] Replace the console-led Live startup with Fedora Server product environment + Cage + Firefox kiosk runtime and secure first-boot bootstrap.
- [x] Read-only block-device, partition and volume inventory.
- [x] Manifest-backed whole-disk and partition capture.
- [x] Verified whole-disk and partition restore engines.
- [x] Direct local disk-to-disk and partition-to-partition clone engines.
- [x] Compression and SHA-256 artifact verification; optional `age` encryption and `minisign` signing integrations exist.
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

See [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) for task-level checklists and acceptance criteria. Immediate priorities are repository credential/provider lifecycle across SSHFS, SFTP, NFS, SMB/CIFS and WebDAV; remote-clone disconnect/restart fault injection; consistent operation telemetry; and Server-side artifact-transfer progress. BitTorrent distribution is a co-equal remote-transport priority: select a maintained client and implement authenticated metadata delivery, verified artifact staging, authorized job binding, cancellation, cleanup, peer/bandwidth policy and multi-Client restore. Broader CA rotation and trust migration are explicitly deferred; the supported PKI scope remains managed CA bootstrap, enrollment/renewal, trust inventory/revocation, Server leaf renewal and Server TLS keypair rotation under the existing CA. CA backup does not provide CA rotation or compromise recovery. Durable local operations now have a root-owned systemd worker, persistent queue/journal, Cockpit status/history and boot-time interrupted-job recovery; live systemd and hardware acceptance remain outstanding. Storage growth and volume-aware workflows, PXE unattended orchestration, documentation and release governance follow. Remote-clone two-machine hardware and real network/storage-provider acceptance are operator-run procedures documented in [ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md). Automated fault-injection and recovery checks remain software test responsibilities.

## Operator-owned validation (optional, not a software completion gate)

The project documents how an operator can build the Fedora 45 ISO and validate it in disposable virtual machines in [BUILD.md](BUILD.md). **Actually building the ISO is not required to complete the software backlog.** The documented procedure is sufficient unless the maintainer separately requests an ISO artifact.

Physical-disk destructive acceptance, BIOS/UEFI boot on target hardware, PXE operation on the deployment network and switch IGMP snooping/querier validation are also operator activities. They must not be reported as passed unless someone actually performs and records them.

Automated unit tests, static checks, shell validation, deterministic frontend installation/build, documentation checks and CI remain project responsibilities. Never claim these checks pass without running them or observing successful CI.
