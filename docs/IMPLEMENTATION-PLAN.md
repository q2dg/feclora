# Feclora completion plan

This document is the dependency-ordered implementation backlog and acceptance contract. It complements ROADMAP.md and FEATURE-MATRIX.md.


## Product target: bootable Live system with six Cockpit workflows

The maintainer's end-user requirements and measurable release gates are defined in [USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.md). That document is authoritative for the six workflows: (1) local disk/partition clone, (2) remote disk/partition clone with DHCP/static networking, (3) capture to SSHFS/SFTP/NFS/SMB/WebDAV/S3, (4) restore from those repositories to one local target, (5) multi-Client restore with manual Feclora boot or PXE, and (6) unattended multi-Client restore. It also defines the Cockpit-first operating modes, security invariants, documentation gates and operator ISO acceptance.

Do not mark a workflow complete because an engine, command builder, protocol primitive or operator acceptance recipe exists. Completion requires an end-to-end Cockpit path, backend/runtime integration, safe authorization and failure handling, progress/results, automated software tests, operator acceptance procedure and a matching published step-by-step guide. In particular, S3 read-only support does not satisfy image capture; SFTP is distinct from SSHFS; current PXE service activation does not equal PXE job handoff; and signed restore-profile primitives do not equal unattended fleet restore.

## Delivery principles
1. Reuse existing engines and security primitives; inspect current code before creating parallel implementations.
2. A feature is complete only when runtime, privileged API, Cockpit workflow, failure handling, automated tests and documentation agree.
3. Destructive operations fail closed, require explicit authorization and verify results.
4. Never persist passwords, private keys, age identities or minisign secret keys in profiles, journals, logs or browser storage.
5. Interrupted writes are never silently resumed; affected destinations remain untrusted until verified or restored.
6. Keep local rescue and Server/Client fleet orchestration separate while sharing storage engines.
7. Never claim hardware/PXE/switch acceptance from unit tests alone.

## P0 — Remote disk-to-disk cloning
Existing foundation: remote_clone runtime, protocol/TLS modules, tests, and the existing persistent Server/Client deployment services.
- [x] Add remote clone as a distinct operation to the existing Server/Client service lifecycle; do not create parallel daemons, IPC or job journals.
- [x] Reuse the existing mTLS control session, enrollment/peer authorization, service locks, durable job records and Cockpit status plumbing.
- [x] Keep the direct block-stream data plane separate from UDPcast: the current UDPcast wrapper transfers signed image artifacts to private staging files for multicast restore; it does not implement direct block-device cloning.
- [x] Extend the existing job definition and privileged API validation for a Server-local read-only source disk; reuse the existing inspect/start/status/arm API and local IPC rather than adding parallel actions.
- [x] Add Cockpit source/peer selection, Client-local target selection, exact destructive confirmation and independent source/receiver authorization.
- [x] Add local Cockpit DHCP/static IPv4 configuration for the currently managed Server or Client, with NetworkManager checkpoint rollback and profile/address verification.
- [x] Bind remote job definitions to an explicitly selected active Server interface/address; document that Client networking is configured from its own Cockpit session.
- [ ] Add a pre-start reachability check to the intended Client endpoint and verify routing/interface selection on both peers; current authenticated inspect/join remains the first end-to-end Client reachability check.
- [ ] Complete Fedora Live acceptance for DHCP/static changes on both roles, including browser/API disconnect during checkpoint and remote clone connectivity.
- [x] Persist operation IDs, job states, errors and terminal verification through the existing operation logs, Client status and Server job journal; expose live byte progress and throughput in Server/Client status.
- [x] Persist bounded Client progress snapshots in the Server journal and expose the last durable checkpoint in history; restart recovery remains audit-only and never resumes disk I/O.
- [ ] Complete disconnect, timeout and service-restart fault injection; document partial-write and GPT-relocation recovery without implying rollback. Active-write cancellation and rollback are explicitly out of scope.
- [ ] Add two-machine integration tests with generated certificates and disposable image-backed devices.
- [x] Update feature matrix and operational guide.
Acceptance: the Server binds the selected source and READY Client target into the session; the receiver independently verifies its local selection; both peers authorize independently; receiver read-back verifies; partial writes are marked untrusted; the persistent service survives browser disconnect.

## P0 — PKI, trust and identity lifecycle
Existing foundation: managed CA bootstrap, Server leaf renewal and Server TLS keypair rotation under the existing CA, Client renewal/enrollment, trust inventory and revocation. Broader CA rotation/migration is deferred and is not part of the currently implemented lifecycle.
- [x] Add a root-owned, atomic CA trust-bundle builder that validates CA constraints, certificate-signing usage, unique SHA-256 fingerprints and bounded PEM inputs. (Local building block only; authenticated package distribution remains pending.)
- [x] Validate Client leaf certificates against any explicitly fingerprinted CA anchor in an imported PEM bundle and retain the complete bundle as the Client trust file.
- [x] Implement Server TLS keypair rotation under the existing CA, distinct from leaf certificate renewal; expose an exact-confirmation Cockpit action that blocks while deployment services are active.
- [ ] Specify and implement minisign signing-key rotation and age recipient/identity rotation separately from TLS PKI.
- [x] Add encrypted offline CA backup to mounted removable media using an independently supplied age recipient; private CA material remains in root-only staging until encrypted.
- [x] Add non-destructive Cockpit backup inspection: age decryption, strict archive/manifest validation, CA fingerprint and key-pair checks; never installs material.
- [ ] Implement verified CA backup restore and compromise recovery; no manual overwrite of a live PKI directory.
- [ ] Expose preflight, per-client status, expiry, progress and rollback in Cockpit.
- [ ] Test mixed-version clients, interrupted rotation, expiry, wrong SAN/fingerprint and lost Server state.
Acceptance: no cutover strands enrolled clients without recovery; private material never enters logs/browser state; stages are auditable and idempotent.

## P0 — Remote repositories and credentials
Repository-related abstractions/tests already exist; inspect and extend them rather than creating a second implementation.
- [x] Inventory current repository code and reconcile the feature matrix.
- [x] Define a provider interface independent of transport.
- [x] Add root-managed SSHFS/NFS/SMB mount lifecycle and Cockpit actions; keep this separate from image-engine integration.
- [x] Report mounted state separately from verified provider/source/type/access-mode identity in Cockpit.
- [ ] Complete the supported local, NFS, SMB/CIFS, SSHFS and SFTP providers; keep SSHFS mounts distinct from SFTP transfers.
- [x] Add optional repository-ID routing for whole-disk/partition capture, restore and partition extraction; resolve only mounted, verified repositories and enforce read-only mounts for writes. Local repository remains the backward-compatible default.
- [x] Expose repository selection and per-repository image inventory in Cockpit; route capture, restore, verification, layout inspection and partition extraction to the selected verified mount.
- Operator acceptance (documented in `ACCEPTANCE-TESTS.md`): run remote-server checks on SSHFS, NFS and SMB/CIFS, including NFS root-squash/ownership and failure/interruption cases. These physical/provider runs are not implementation blockers.
- [ ] Store credential references in root-owned protected storage; never ordinary config/logs.
- [x] Validate referenced secret files through `O_NOFOLLOW` descriptors and `fstat`; reject symlinks, unsafe ownership/modes and hard-linked credential files.
- [ ] Add SSH host-key pinning, key selection, permission checks and credential rotation.
- [x] Add a root-only local credential-store primitive for SSH keys, known_hosts, SMB files and rclone configs, with atomic create/replace/remove and strict file validation. This is not exposed through Cockpit and does not complete credential administration.
- [x] Add an initial systemd-creds-backed encrypted credential store and transient per-repository mount services using `LoadCredentialEncrypted=` for SSHFS, SMB and rclone. The mount helper consumes credentials only from `$CREDENTIALS_DIRECTORY`; encrypted WebDAV references are explicitly rejected because root-invoked davfs2 uses the global secrets file.
- [x] Add a local root-only credential import/removal CLI that reads protected source files, plus a read-only Cockpit API inventory of validated credential references; the API never accepts or returns secret material.
- [ ] Integrate Fedora `oo7-daemon` Secret Service with interactive operator-session workflows where a user bus is available; never make unattended Server jobs depend on that session.
- [ ] Design and implement a safe per-repository WebDAV credential lifecycle compatible with davfs2's root-mount semantics; do not use or mutate the global `/etc/davfs2/secrets` as a multi-repository workaround. Extend encrypted service credentials to other long-running Server jobs; migrate existing plaintext credential references and remove the legacy plaintext store/CLI only after compatibility and recovery paths are covered.
- [ ] Add Cockpit credential selection and repository edit/test/health workflows, WebDAV secret lifecycle, provider-aware S3 artifact publication and automated mount-lifecycle coverage.
- [ ] Handle stale mounts, network loss, interrupted publication, concurrent writers and cleanup.
- [ ] Add integration tests with local test services where practical.
Acceptance: engines use repository IDs/handles, secrets are redacted, failures cannot leave falsely complete images.

## P0 — Durable operations and progress
Existing foundation: deployment journals, persistent Server service lifecycle, root-only Unix-socket control, Client progress and local operation log. Architecture decision: [ADR 0010](adr/0010-durable-local-operations.md).
- [x] Define a versioned local-operation state machine and hash-chained event schema without changing existing deployment journals.
- [x] Move local long-running capture/restore/clone work out of the Cockpit/API request process into a root-owned systemd worker independent of UI sessions.
- [x] Make Cockpit submit validated jobs and consume durable operation IDs, status and progress; browser disconnection does not own worker execution.
- [x] Persist queued, preflight, running, verifying, completed, failed and interrupted states; active destructive writes are deliberately non-cancellable.
- [ ] Report bytes, phase, throughput, timestamps and bounded diagnostic categories consistently across every local operation.
- [x] Detect unfinished local operations across reboot and mark them interrupted for manual review; never resume destructive I/O automatically. Verify and harden detached-worker supervision on live systemd hosts.
- [x] Add process-independent per-device locks/conflict detection while preserving the existing host-wide storage/deployment exclusion.
- [x] Expose local operation history and event detail in Cockpit; export and richer filtering remain pending.
- [ ] Add Server-side artifact-transfer progress; separate control/data channels if required.
- [ ] Keep `dialog`/ `zenity` out of the execution architecture; any future console UI must be a client of the same durable service. The legacy `dialog_app.py` still executes engines in its own process and is not safe to reactivate as-is.
Acceptance: browser closure does not stop jobs; history survives Cockpit/API and worker service restarts; destructive jobs cannot race on one device; restart never silently resumes writes; all UI clients use the same validation and authorization boundary.

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
- [ ] Add automated BIOS/UEFI PXE tests in virtual networks; physical switch/IGMP acceptance remains operator-owned and is documented in `ACCEPTANCE-TESTS.md`.
Acceptance: PXE boot alone never authorizes writes; each client verifies signed, unexpired, single-use authorization and target identity.

## P1 — GitHub Pages guides
Publish task-oriented guides only when the exact workflow is implemented; mark future workflows as planned.
1. [x] Local disk-to-disk clone ([published guide](GUIDE-LOCAL-DISK-CLONE.md)).
2. [x] Remote disk-to-disk clone ([operational guide](REMOTE-DISK-CLONE.md)).
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

## Operator acceptance guides

- [x] Publish step-by-step operator procedures for physical two-machine clone, multi-Client unicast/multicast restore, SSHFS/NFS/SMB/WebDAV repository checks, S3 read-only checks, interruption/restart recovery and repository lease protection ([ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md)).
- [ ] Hardware, network and real remote-service acceptance runs remain operator-owned; record results rather than treating them as code implementation.

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
- Authorization, secret handling and failure semantics are documented. Active destructive disk writes are non-cancellable and have no rollback guarantee.
- Automated tests cover normal, invalid, interrupted and adversarial cases.
- Relevant CI checks pass.
- Feature matrix, roadmap and user docs match implementation.
- Unsupported scenarios are not advertised as supported.

## Explicitly not assumed
- No automatic destructive resume after interruption.
- No automatic filesystem growth without an explicitly selected policy.
- No multicast capture, concurrent unicast fleet deployment or Wake-on-LAN unless separately approved.
- No mandatory ISO build or physical lab run for software-backlog completion.

## Network configuration implementation checkpoint

A read-only NetworkManager connection-profile inventory is available to the
Cockpit API. It reports sanitized profile metadata and IPv4 configuration
without returning connection secrets. This is preparatory infrastructure only.
Still required for the DHCP/static networking acceptance gate:

- Cockpit controls to select the Server or Client role and a NetworkManager
  connection profile;
- validated DHCP and static IPv4 configuration, including prefix, gateway
  and DNS handling;
- safeguards against changing the management path without explicit warning
  and a recoverable apply/rollback strategy;
- post-apply address, route and DNS verification, with clear failure reporting;
- Client-side configuration integrated with enrollment and remote-job
  interface selection;
- automated tests for validation, command construction, failure and rollback,
  followed by non-E2E operational acceptance on Fedora hardware.

The inventory endpoint does not apply network changes and does not close this
acceptance gate.


## DHCP/static NetworkManager apply checkpoint

The Cockpit Network tab now exposes a first usable IPv4 configuration path on
the current host, whether operating as deployment Server or Client. It lists
sanitized NetworkManager connection profiles, applies DHCP or static IPv4
settings to an active profile, activates it, and verifies the active profile
and resulting address. NetworkManager D-Bus checkpoints provide a 120-second
automatic rollback window; Feclora destroys the checkpoint only after
verification and requests rollback on an error.

This is an initial implementation, not yet a release acceptance pass. The
remaining networking gate includes Fedora 45 runtime validation of the
NetworkManager D-Bus checkpoint calls and rollback semantics, DHCP lease and
static route/DNS verification, recovery after browser/API disconnection,
inactive profile selection, and the full Server/Client enrollment and remote
clone workflow. The current verifier checks profile activation and address;
gateway reachability, DNS resolution and end-to-end remote connectivity are
not yet acceptance-tested.
