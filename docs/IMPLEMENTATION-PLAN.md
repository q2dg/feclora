# Feclora completion plan

This document is the dependency-ordered implementation backlog and acceptance contract. It complements ROADMAP.md and FEATURE-MATRIX.md.

## Delivery principles
1. Reuse existing engines and security primitives; inspect current code before creating parallel implementations.
2. A feature is complete only when runtime, privileged API, Cockpit workflow, failure handling, automated tests and documentation agree.
3. Destructive operations fail closed, require explicit authorization and verify results.
4. Never persist passwords, private keys, age identities or minisign secret keys in profiles, journals, logs or browser storage.
5. Interrupted writes are never silently resumed; affected destinations remain untrusted until verified or restored.
6. Keep local rescue and Server/Client fleet orchestration separate while sharing storage engines.
7. Never claim hardware/PXE/switch acceptance from unit tests alone.

## P0 — Remote disk-to-disk cloning
Existing foundation: remote_clone runtime, protocol/TLS modules, tests and REMOTE-DISK-CLONE.md.
- [ ] Integrate source and receiver roles with persistent Server/Client services.
- [ ] Add least-privilege API actions for preflight, authorize, start, inspect and cancel.
- [ ] Add Cockpit device/peer selection, peer identity verification, exact destructive confirmation and dual-operator authorization.
- [ ] Persist operation IDs, states, bytes, throughput, errors and terminal verification on both endpoints.
- [ ] Handle disconnects, timeouts, service restart, cancellation and GPT relocation without implying rollback.
- [ ] Add integration tests with generated certificates and disposable image-backed devices.
- [ ] Update feature matrix and add an operational guide.
Acceptance: remote headers cannot select local devices; both peers authorize independently; receiver read-back verifies; partial writes are marked untrusted; UI survives browser disconnect.

## P0 — PKI, trust and identity lifecycle
Existing foundation: managed CA bootstrap, Server leaf renewal under the existing CA, Client renewal/enrollment, trust inventory and revocation.
- [ ] Define versioned trust-bundle and migration formats.
- [ ] Implement staged CA rotation with old/new trust overlap, client migration accounting, explicit activation and rollback.
- [ ] Implement Server TLS keypair rotation, distinct from leaf certificate renewal.
- [ ] Specify and implement minisign signing-key rotation and age recipient/identity rotation separately from TLS PKI.
- [ ] Add encrypted offline backup/restore and compromise recovery.
- [ ] Expose preflight, per-client status, expiry, progress and rollback in Cockpit.
- [ ] Test mixed-version clients, interrupted rotation, expiry, wrong SAN/fingerprint and lost Server state.
Acceptance: no cutover strands enrolled clients without recovery; private material never enters logs/browser state; stages are auditable and idempotent.

## P0 — Remote repositories and credentials
Repository-related abstractions/tests already exist; inspect and extend them rather than creating a second implementation.
- [x] Inventory current repository code and reconcile the feature matrix.
- [x] Define a provider interface independent of transport.
- [x] Add root-managed SSHFS/NFS/SMB mount lifecycle and Cockpit actions; keep this separate from image-engine integration.
- [ ] Complete the supported local, NFS, SMB/CIFS, SSHFS and SFTP providers; keep SSHFS mounts distinct from SFTP transfers.
- [ ] Store credential references in root-owned protected storage; never ordinary config/logs.
- [ ] Add SSH host-key pinning, key selection, permission checks and credential rotation.
- [ ] Complete Cockpit create/edit/test/mount/unmount/read-only/delete workflows and health/free-space reporting; create/mount/unmount/remove are present for SSHFS/NFS/SMB, but edit/test/health and provider identity checks remain.
- [ ] Handle stale mounts, network loss, interrupted publication, concurrent writers and cleanup.
- [ ] Add integration tests with local test services where practical.
Acceptance: engines use repository IDs/handles, secrets are redacted, failures cannot leave falsely complete images.

## P0 — Durable operations and progress
Existing foundation: deployment journals, Server service lifecycle, Client progress and local operation log.
- [ ] Define a common versioned operation state machine/event schema.
- [ ] Move local long-running capture/restore/clone work out of browser request lifecycle.
- [ ] Persist queued, preflight, running, verifying, completed, failed, cancelled and interrupted states.
- [ ] Report bytes, phase, throughput, timestamps and diagnostic categories.
- [ ] Define safe cancellation boundaries and non-cancellable phases.
- [ ] Reconcile stale workers after restart without automatic destructive resume.
- [ ] Add per-device locks/conflict detection.
- [ ] Expose operation history/detail/cancel/export in Cockpit.
- [ ] Add Server-side artifact-transfer progress; separate control/data channels if required.
Acceptance: browser closure does not stop jobs; history survives service restart; destructive jobs cannot race on one device; restart never silently resumes writes.

## P1 — Storage topology and explicit growth
Existing foundation: block inventory, read-only LVM reporting, Btrfs/Stratis inventory, restore profiles and whole-disk layout preview.
- [ ] Normalize read-only topology: disk → partition → crypto mapping → PV/VG/LV → filesystem/subvolume/pool/device.
- [ ] Represent unknown, degraded, missing and unsupported layers explicitly.
- [ ] Add previewable policies: preserve, expand-last-compatible, fixed sizes, proportional and manual.
- [ ] Validate alignment, sector size, geometry and EFI/BIOS/recovery partition roles.
- [ ] Implement filesystem-aware growth only for explicitly supported combinations.
- [ ] Add LUKS header backup and distinguish encrypted-container copy from decrypted migration.
- [ ] Complete LVM capture/restore including PV/VG/LV and thin-provisioning constraints.
- [ ] Complete Btrfs multi-device/profile/subvolume/snapshot handling and UUID collision strategy.
- [ ] Complete Stratis pool/device/filesystem handling and recovery constraints.
- [ ] Add Cockpit topology views and explicit restore plans.
Acceptance: inventory never implies restore support; mutations have a read-only plan, explicit consent, compatibility checks and post-operation verification.

## P1 — PXE and unattended fleet restore
Existing foundation: PXE/iPXE lifecycle, unicast/multicast restore, signed profile model and single-use executor.
- [ ] Add Cockpit profile authoring, review, signing and revocation.
- [ ] Integrate profiles with PXE boot selection and client identity authorization.
- [ ] Implement safe layout policies; proportional growth stays unavailable until each filesystem combination is supported.
- [ ] Add client groups and stable-identity target matching.
- [ ] Add per-client preflight, staging space, signature and expiry reporting.
- [ ] Define retry behavior that cannot replay single-use authorization.
- [ ] Add per-client verification and exportable deployment reports.
- [ ] Test BIOS/UEFI PXE in virtual networks; physical switch/IGMP acceptance remains operator-owned.
Acceptance: PXE boot alone never authorizes writes; each client verifies signed, unexpired, single-use authorization and target identity.

## P1 — GitHub Pages guides
Publish task-oriented guides only when the exact workflow is implemented; mark future workflows as planned.
1. [x] Local disk-to-disk clone ([published guide](GUIDE-LOCAL-DISK-CLONE.md)).
2. [ ] Remote disk-to-disk clone.
3. [ ] Capture disk image to remote SSHFS repository.
4. [ ] Restore image from SSHFS to one disk.
5. [ ] Restore image to multiple remote clients.
6. [ ] Restore multiple clients using PXE.
7. [ ] Unattended multi-client PXE restore.
8. [ ] Initial Server/Client setup, enrollment and trust.
9. [ ] Repository and credential administration.
10. [ ] Advanced storage: LVM, LUKS, Btrfs and Stratis.
11. [ ] Interrupted-operation and PKI recovery.

The [guide index](GUIDES.md) distinguishes available procedures from planned
workflows. Do not publish an operational recipe for an unimplemented path.
Every guide needs prerequisites, supported layouts, exact Cockpit steps, expected results, verification, failure recovery and data-loss warnings. Use current screenshots and role/network diagrams.

## P1 — Governance and release engineering
- [x] Maintainer selected and published GNU GPL v3.0 or later (`GPL-3.0-or-later`) in the repository root LICENSE file.
- [ ] Add reproducible frontend lockfile and deterministic CI installation.
- [ ] Reconcile README, Cockpit README, roadmap, feature matrix and operator docs.
- [ ] Add dependency/security scanning and secret-leak checks.
- [ ] Define Fedora baseline and dependency/version policy.
- [ ] Document configuration/key backup, upgrades, rollback and disaster recovery.
- [ ] Document release checksums/signatures and provenance.

## ISO build and acceptance policy
Actually building the ISO is NOT a required completion gate. The documented build procedure is sufficient documentation of how an operator can produce it. Do not spend implementation time generating or publishing an ISO unless the maintainer explicitly requests it.

This does not waive software-level checks: Python tests, static checks, frontend dependency installation/build, CI, shell-script validation and documentation/link checks remain project responsibilities. Keep build instructions/scripts maintained, but an actual ISO build, BIOS/UEFI boot, destructive physical-disk test, target-network PXE boot and switch/IGMP validation are optional operator activities, not prerequisites for completing the software backlog.

## Definition of done
- Implementation and Cockpit integration are present where applicable.
- Authorization, secret handling, failure and cancellation semantics are documented.
- Automated tests cover normal, invalid, interrupted and adversarial cases.
- Relevant CI checks pass.
- Feature matrix, roadmap and user docs match implementation.
- Unsupported scenarios are not advertised as supported.

## Explicitly not assumed
- No automatic destructive resume after interruption.
- No automatic filesystem growth without an explicitly selected policy.
- No multicast capture, concurrent unicast fleet deployment or Wake-on-LAN unless separately approved.
- No mandatory ISO build or physical lab run for software-backlog completion.