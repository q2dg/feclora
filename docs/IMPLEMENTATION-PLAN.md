# Feclora completion plan

This document is the dependency-ordered implementation backlog and acceptance contract. It complements ROADMAP.md and FEATURE-MATRIX.md.


## Product target: Fedora Server minimal Live kiosk with six Cockpit workflows

The maintainer's end-user requirements and measurable release gates are defined in [USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.md). That document is authoritative for the six workflows: (1) local disk/partition clone, (2) remote disk/partition clone with DHCP/static networking, (3) capture to SSHFS/SFTP/NFS/SMB/WebDAV, (4) restore from those repositories to one local target, (5) multi-Client restore with manual Feclora boot or PXE, and (6) unattended multi-Client restore. BitTorrent is a first-class distribution transport for immutable artifacts, at the same implementation priority as SSHFS, SFTP, NFS, SMB/CIFS and WebDAV; it is not a writable repository. It also defines the Cockpit-first operating modes, security invariants, documentation gates and operator ISO acceptance. The Live image is based on a minimal Fedora Server userspace without a general-purpose desktop; Cage launches Firefox in kiosk mode against the local Cockpit endpoint.

Do not mark a workflow complete because an engine, command builder, protocol primitive or operator acceptance recipe exists. Completion requires an end-to-end Cockpit path, backend/runtime integration, safe authorization and failure handling, progress/results, automated software tests, operator acceptance procedure and a matching published step-by-step guide. In particular, SFTP is distinct from SSHFS; the new PXE answer path now downloads and validates JSON in Live and connects NFS-backed whole-disk restore to the existing engine with stable-target revalidation. Remaining PXE work includes other repository providers, replay/expiry controls, Cockpit result reporting and physical acceptance. The standalone signed restore-profile executor is separate from this PXE answer workflow.

## Delivery principles
1. Reuse existing engines and mature system tools; inspect current code before creating parallel implementations. Prefer Partclone for supported filesystems, UDPcast for multicast, NetworkManager for network configuration/checkpoints, OpenSSL for TLS/X.509 operations, systemd for services/workers/credentials, and established SSH/SFTP, NFS, SMB, davfs2 implementations for transport/storage. Select and integrate a maintained BitTorrent client rather than implementing the protocol.
2. A feature is complete only when runtime, privileged API, Cockpit workflow, failure handling, automated tests and documentation agree.
3. Destructive operations fail closed, require explicit authorization and verify results.
4. Never persist passwords, private keys, `age` identities or `minisign` secret keys in profiles, journals, logs or browser storage. `age` and `minisign` are optional integrations, not mandatory packages or release gates; preserve a safe non-age/non-minisign workflow and document the configured authenticity mechanism.
5. Interrupted writes are never silently resumed; affected destinations remain untrusted until verified or restored.
6. Keep local rescue and Server/Client fleet orchestration separate while sharing storage engines.
7. Treat kiosk confinement as defense in depth; never use it as a replacement for Cockpit authentication, OS account separation or backend authorization.
8. Never claim hardware/PXE/switch acceptance from unit tests alone.

## P0 — Live appliance startup, kiosk and first-boot security

Target architecture: a bootable Live ISO using a minimal Fedora Server
userspace, with no general-purpose desktop environment. Cockpit is enabled
through `cockpit.socket`. A minimal Wayland compositor (Cage) launches Firefox
in kiosk mode on the local display, fixed to the local Cockpit endpoint and
Feclora application. The Live boot model must be preserved; this is not a
migration to an installed-only Fedora Server appliance.

- [x] Replace the generic minimal Kickstart environment with the Fedora Server
  product environment while retaining the Live initramfs, BIOS/UEFI boot and
  Lorax image pipeline.
- [x] Add Cage and Firefox to the runtime package manifest and keep the
  Kickstart and package manifest synchronized.
- [x] Implement a dedicated unprivileged kiosk account and a systemd-managed
  Cage/Firefox session on the local display, with automatic restart.
- [x] Configure Firefox kiosk mode and a managed policy with a Cockpit/setup
  `WebsiteFilter` exceptions for the setup/Cockpit origins, browser password
  storage disabled and developer tools blocked.
- [x] Configure Cockpit socket activation and order it after local TLS
  certificate provisioning; start the kiosk after Cockpit and bootstrap.
- [x] Implement a loopback-only first-boot form that sets a unique administrator
  password (minimum 14 characters) without a default/shared secret or browser
  storage. The administrator account remains locked until this succeeds.
- [x] Generate a local Cockpit CA and localhost/IP SAN certificate, install
  the CA into the system trust store and Firefox's Linux `Certificates.Install`
  policy.
- [x] Keep Live-session credentials, local CA/private key and temporary
  configuration ephemeral. Each boot starts a new session and regenerates
  these values; persistence across Live reboots is not a requirement. Images,
  manifests and other durable artifacts are written only to explicitly selected
  external repositories. No implicit target-disk selection is permitted.
- [x] Define the authorized administrator and kiosk account privilege
  boundaries; the kiosk account is not a member of wheel and cannot log in
  to Cockpit as an administrator or invoke privileged Feclora API actions.
- [x] Remove console autologin and passwordless sudo, run Firefox under a
  separate non-wheel nologin account, mask tty1–tty6 getty services, restrict
  Firefox navigation through enterprise policy and deny non-loopback network
  access to the kiosk/bootstrap services using systemd IP filters.
- [ ] Verify compositor/keyboard escape paths and the Cockpit Terminal
  experience on real hardware. The administrator's authenticated Cockpit
  Terminal remains an administrative capability; kiosk mode is not a
  security boundary against a user with administrator credentials.
- [x] Keep Cockpit's authenticated Terminal feature subject to administrator
  authorization; the kiosk account has no Cockpit administrator credentials.
- [x] Add static validation for package/service/policy wiring and unit tests
  for first-boot password validation and account provisioning.
- [x] Update operator documentation and acceptance tests for cold boot,
  Cockpit TLS trust, login/bootstrap, browser restart, TTY escape attempts,
  keyboard shortcuts and Firefox failure recovery.
- [ ] Validate on BIOS and UEFI VMs and representative physical display/input
  hardware. ISO creation remains operator-owned and is not part of this task.

Acceptance still requires operator execution: a cold BIOS/UEFI boot must reach the local setup form and then Cockpit without presenting a desktop or shell; Firefox must remain confined to the allowlisted local origins; the generated certificate must be trusted; the administrator must authenticate with the password created at first boot; and the kiosk account must not invoke privileged backend operations.

## P0 — Remote disk-to-disk cloning
Existing foundation: remote_clone runtime, protocol/TLS modules, tests, and the existing persistent Server/Client deployment services.
- [x] Add remote clone as a distinct operation to the existing Server/Client service lifecycle; do not create parallel daemons, IPC or job journals.
- [x] Reuse the existing mTLS control session, enrollment/peer authorization, service locks, durable job records and Cockpit status plumbing.
- [x] Keep the direct block-stream data plane separate from UDPcast: the current UDPcast wrapper transfers signed image artifacts to private staging files for multicast restore; it does not implement direct block-device cloning.
- [x] Extend the existing job definition and privileged API validation for a Server-local read-only source disk; reuse the existing inspect/start/status/arm API and local IPC rather than adding parallel actions.
- [x] Add Cockpit source/peer selection, Client-local target selection, exact destructive confirmation and independent source/receiver authorization.
- [x] Add local Cockpit DHCP/static IPv4 configuration for the currently managed Server or Client, with NetworkManager checkpoint rollback and profile/address verification.
- [x] Bind remote job definitions to an explicitly selected active Server interface/address; document that Client networking is configured from its own Cockpit session.
- [x] Expose the Client's pre-start authenticated reachability check in Cockpit: inspect the job over TLS and verify the enrolled Server identity before local target approval.
- [x] Expose Client interface/address selection in Cockpit and bind both the authenticated preflight and persistent Client TLS session to that source IPv4 address; revalidate address ownership immediately before each connection.
- [x] Verify each resolved Server IPv4 route with `ip route get` before Client preflight and persistent TLS connections; fail closed unless the kernel selects the requested interface and source address. Per-job policy-route/table selection and route pinning remain pending.
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
- [x] Make age identity/recipient provisioning optional for baseline enrollment, renewal and deployment. TLS-only enrollment/renewal accepts no age material; renewal does not create an age identity when none is configured. The CA-backup operation remains a separate, explicitly age-encrypted optional feature.
- [x] Remove mandatory minisign from baseline unicast save/restore and multicast restore. These paths authenticate the manifest over the enrolled mTLS session and verify a detached minisign signature when present; age decryption is required only for artifacts marked age-encrypted.
- [ ] Introduce a configurable signature-verifier interface for the optional signed unattended-profile and SFTP image-set workflows; minisign remains their current implementation and is not a baseline deployment dependency.
- [ ] If configured, specify and implement signing-key rotation and age recipient/identity rotation separately from TLS PKI. These optional integrations must not block the baseline product or release.
- [x] Add encrypted offline CA backup to mounted removable media using an independently supplied age recipient; private CA material remains in root-only staging until encrypted.
- [x] Add non-destructive Cockpit backup inspection: age decryption, strict archive/manifest validation, CA fingerprint and key-pair checks; never installs material.
- [ ] Implement verified CA backup restore and compromise recovery; no manual overwrite of a live PKI directory.
- [ ] Expose preflight, per-client status, expiry, progress and rollback in Cockpit.
- [ ] Test mixed-version clients, interrupted rotation, expiry, wrong SAN/fingerprint and lost Server state.
Acceptance: no cutover strands enrolled clients without recovery; private material never enters logs/browser state; stages are auditable and idempotent.

## P0 — Remote repositories and credentials
Repository-related abstractions/tests already exist; inspect and extend them rather than creating a second implementation. Architectural boundary: every SSH/SFTP, NFS, SMB/CIFS, WebDAV and BitTorrent service is external and independently administered. Feclora implements client-side connection, credential handling, mount/transfer, integrity, lifecycle of its own client processes, and failure reporting only; it does not deploy or configure remote servers, exports, shares, trackers or peers.
- [x] Inventory current repository code and reconcile the feature matrix.
- [x] Define a provider interface independent of transport.
- [x] Add root-managed SSHFS/NFS/SMB mount lifecycle and Cockpit actions; keep this separate from image-engine integration.
- [x] Report mounted state separately from verified provider/source/type/access-mode identity in Cockpit.
- [x] Add an initial standalone OpenSSH SFTP file-transfer primitive with pinned host keys, staged hard-link no-overwrite upload, and SHA-256-verified download; keep it separate from SSHFS mounts.
- [x] Add systemd-creds-backed SFTP transfer execution and signed image-set publish/fetch primitives with minisign and artifact digest verification.
- [ ] Close SSHFS/NFS/SMB provider acceptance gaps as a shared mounted-filesystem track: stale-mount and network-loss recovery, provider health/free-space telemetry, single-publisher publication behavior, concurrent reader/restore access, interrupted capture/publication cleanup, permission semantics and end-to-end Cockpit capture/restore tests. Mount identity inspection is bounded to five seconds, but does not probe remote filesystem I/O; never add unbounded stat/statvfs probes for hard-mounted NFS. Add NFS root-squash/ownership coverage without weakening manifest ownership checks.
- [ ] Complete SFTP as a distinct file-transfer track: multi-directory inventory/discovery, continuous byte-level progress within files, safe recovery/resume policy, provider health checks and operational acceptance. Inventory, import and publication are durable/cancellable; metadata inspection remains synchronous. Artifact-boundary progress is journaled. Bounded retries for transient read-only transfers are implemented; upload retries remain deliberately disabled.
- [ ] Complete safe WebDAV per-repository credential isolation and provider lifecycle; do not depend on the global davfs2 secrets file. Keep the provider unavailable until isolated credentials and HTTPS certificate validation are tested.
- [ ] Implement BitTorrent immutable-artifact distribution at the same priority as the other remote transports, using a maintained client, trusted manifest/digest verification, authorized job binding, cancellation, incomplete-download cleanup, peer/bandwidth policy, multi-Client restore and acceptance tests. It is a distribution transport, not a writable repository.
- [ ] Maintain transport-specific acceptance records at equal priority: SSHFS, NFS, SMB/CIFS, WebDAV and SFTP must state supported read/write operations, credential lifecycle, progress/cancellation, interruption/recovery semantics, automated coverage and operator acceptance.
- [ ] BitTorrent acceptance must cover publication/seeding, authenticated metadata delivery, download/restore, independent authenticity and digest verification, authorization binding, cancellation, cleanup, peer/bandwidth policy, concurrent readers and operator acceptance. It has the same priority and release-gate rigor, with distribution-specific semantics rather than mounted-filesystem behavior.
- [x] Add optional repository-ID routing for whole-disk/partition capture, restore and partition extraction; resolve only mounted, verified repositories and enforce read-only mounts for writes. Local repository remains the backward-compatible default.
- [x] Expose repository selection and per-repository image inventory in Cockpit; route capture, restore, verification, layout inspection and partition extraction to the selected verified mount.
- Operator acceptance (documented in `ACCEPTANCE-TESTS.md`): run SSHFS, NFS and SMB/CIFS checks independently, including NFS root-squash/ownership, permissions, disconnects and interrupted capture/restore. These real-server runs remain outstanding; they are not substitutes for automated software tests.
- [x] Store repository credential references as host-bound encrypted systemd credential blobs under root-only storage; never persist plaintext in ordinary config/logs.
- [x] Validate referenced secret files through `O_NOFOLLOW` descriptors and `fstat`; reject symlinks, unsafe ownership/modes and hard-linked credential files.
- [x] Enforce SSH host-key pinning with strict checking and a selected `known_hosts` reference; expose encrypted SSH key/known-hosts selection in Cockpit and validate ownership, mode, link count and symlink safety. Encrypted credential replacement is available; live rotation/reconnect acceptance remains pending.
- [x] Add the root-only credential-store primitive and Cockpit import/removal of protected local source files into host-bound systemd-creds blobs; Cockpit lists metadata and preserves references when removal is attempted. Full credential rotation/recovery acceptance remains pending.
- [x] Add an initial systemd-creds-backed encrypted credential store and transient per-repository mount services using `LoadCredentialEncrypted=` for SSHFS and SMB. The mount helper consumes credentials only from `$CREDENTIALS_DIRECTORY`; encrypted WebDAV references are explicitly rejected because root-invoked davfs2 uses the global secrets file.
- [x] Add a local root-only credential import/removal CLI that reads protected source files, plus a read-only Cockpit API inventory of validated credential references; the API never accepts or returns secret material.
- [ ] Integrate Fedora `oo7-daemon` Secret Service with interactive operator-session workflows where a user bus is available; never make unattended Server jobs depend on that session.
- [ ] Design and implement a safe per-repository WebDAV credential lifecycle compatible with davfs2's root-mount semantics; do not use or mutate the global `/etc/davfs2/secrets` as a multi-repository workaround. Extend encrypted service credentials to other long-running Server jobs; migrate existing plaintext credential references and remove the legacy plaintext store/CLI only after compatibility and recovery paths are covered.
- [x] Add Cockpit import/removal of protected local credential files into systemd-creds storage, read-only encrypted-reference inventory, and credential selection for SSHFS and SMB repositories.
- [x] Add Cockpit repository definition editing while unmounted, explicit mount-identity inspection (findmnt source/type/access-mode comparison only; not a live health or I/O probe), and safe reference-preserving credential removal.
- [x] Serialize repository registry add/update/remove transactions across processes with a private root-owned lock; reload the registry under lock, cover concurrent adds, symlinked-lock rejection and failed-removal rollback with unit tests.
- [ ] Add safe WebDAV per-repository encrypted credentials and isolated davfs2 service configuration; and automated mount-lifecycle coverage. WebDAV is rejected by validation and is not a supported managed provider today.
- [ ] Handle stale mounts, network loss, interrupted publication, cleanup, and concurrent read/restore access to committed images under the single-publisher / multi-reader model. Concurrent publishers for the same image are out of scope.
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

## P1 — Filesystem-aware partition imaging

Existing foundation: filesystem-specific Partclone command selection for ext2/ext3/ext4, XFS, NTFS (including the Linux `ntfs3` FSTYPE alias), FAT12/16/32/vfat, exFAT, F2FS and Btrfs partition images; raw `dd` fallback for unknown filesystems or unavailable capture utilities; matching restore mappings and post-restore checkers; raw read-back verification.

- [x] Keep capture and restore filesystem-to-Partclone mappings aligned, including NTFS FSTYPE aliases.
- [x] Require a defined post-restore checker for every filesystem-specific Partclone restore mapping.
- [x] Preserve explicit raw capture fallback when Partclone is unavailable or the filesystem is unknown; record the known filesystem identifier when possible.
- [ ] Validate every listed filesystem against real disposable filesystems and the exact Fedora package/tool versions shipped; record capture, restore, checker and data-integrity outcomes.
- [ ] Verify dirty/unclean filesystem handling and mounted/in-use source behavior for each filesystem; reject unsafe capture rather than silently claiming a consistent image.
- [ ] Define and document unsupported filesystem variants and Partclone version limitations; never infer support from kernel recognition or a manifest allowlist alone.
- [ ] Ensure Cockpit reports the selected capture engine (Partclone or raw dd), the reason for fallback and the post-restore verification method.

Acceptance: each supported filesystem has a matching capture/restore mapping, a safe verification path and a recorded real-filesystem round trip. If filesystem-aware capture is unavailable, raw imaging remains an explicit fallback, not an assertion of filesystem-aware optimization.

## P1 — Storage discovery and image fidelity
Scope clarification: LVM logical volumes, LUKS2 containers/open mappings, Btrfs filesystems and Stratis-backed devices are storage source layers/types to inventory and image, not repository or transport types. Repositories/transports are the separate external destinations and distribution mechanisms (SSHFS, SFTP, NFS, SMB/CIFS, WebDAV and BitTorrent). This is an image-creation and restore-compatibility requirement, not a request for Feclora to administer storage stacks or provision them. Feclora must discover and describe existing layers accurately, then capture the selected block-level or filesystem-level content without silently flattening or omitting them.
Existing foundation: block inventory, read-only LVM reporting, Btrfs/Stratis inventory, restore profiles and whole-disk layout preview.
- [x] Add a conservative read-only storage graph joining lsblk disk/partition ancestry, LUKS2 containers and active crypt mappings, exact-path LVM PV/VG/LV relationships, filesystem signatures, Btrfs multi-device membership and discovered subvolume/snapshot provenance. Unmatched aliases and missing devices are reported as unresolved; no path aliases or ancestry are guessed.
- [x] Extend the graph with Btrfs mount-source UUID linkage, Btrfs filesystem-to-subvolume membership and Stratis pool/filesystem/backing-device membership. Mount UUIDs and Stratis device paths are joined only when exact inventory evidence matches; unmatched paths remain unresolved.
- [x] Resolve LVM LV aliases to lsblk block devices using the active kernel major/minor identity reported by LVM and lsblk. A major/minor match must be unique; ambiguous or unavailable identities remain unresolved, and even an exact path match is rejected if both reported major/minor identities conflict. Link matched LVs to discovered filesystem nodes without relying on mapper path spelling.
- [x] Extend read-only LVM reports with PV/VG/LV membership, physical/free extents, thin-pool and snapshot indicators, missing-PV counts/attributes, and LV health summaries. Preserve raw LVM rows and report degraded or unknown VG health conservatively. Automated tests added; Fedora 45 runtime compatibility and real missing-PV/thin-pool fixtures still require validation.
- [x] Discover subvolumes on already-mounted Btrfs filesystems and distinguish snapshots from ordinary subvolumes using parent UUID metadata; record received UUID provenance separately without assuming every received subvolume is a snapshot.
- [x] Extend read-only Btrfs inventory for already-mounted filesystems with Data/Metadata/System/GlobalReserve allocation profiles, preserving unknown profile names rather than normalizing them to a supported mode. Attach profile observations to the storage graph; do not mount or modify filesystems.
- [ ] Extend Btrfs discovery to unmounted filesystems without mounting them, capture snapshot/subvolume ancestry and backing-device/profile dependencies, and validate snapshot consistency.
- [x] Tag LUKS container signatures and active `crypt` device-mapper mappings in the read-only `lsblk` inventory; no passphrases are requested or stored.
- [x] Inspect LUKS2 headers read-only with `cryptsetup`: UUID, cipher, sector size where available, and keyslot/token/segment counts. Do not expose token payloads or request/store passphrases.
- [x] Distinguish raw LUKS2 container bytes (including header/keyslots) from plaintext bytes read through an opened crypt mapping in capture planning; nested LUKS containers do not change a whole-disk image's byte scope. Never request or persist passphrases in ordinary profiles, logs or browser state.
- [ ] Represent unknown, degraded, missing and unsupported layers explicitly; never present discovery as proof that capture or restore is supported.
- [x] Connect the layer-aware capture planner to the Cockpit partition-image capture path. Raw LUKS2 partition images are stored as encrypted-container bytes only after `cryptsetup` verifies a version-2 header (including headers/keyslots, never passphrases); LUKS1 and unknown headers fail closed with LUKS UUID provenance; supported single-device Btrfs partition images record filesystem UUID/dependency provenance and continue to use `partclone.btrfs`. Incomplete multi-device Btrfs selections fail closed.
- [x] Add a read-only capture planner for whole-disk, partition and logical-volume byte scope; distinguish raw LUKS2 containers from opened crypt mappings; report nested LUKS/LVM dependencies; check LV/VG metadata dependencies and multi-device Btrfs completeness; block mounted/in-use sources. The planner is a safety/metadata primitive only; it does not execute capture or create snapshots.
- [x] Extend image manifests with a distinct logical-volume image type/artifact role and strictly validated storage metadata for byte scope, LUKS2 UUID, LVM VG/LV identity, Btrfs filesystem/subvolume provenance, Btrfs device count and explicit dependency identities. Capture planning emits portable LVM/LUKS metadata; older disk/partition manifests remain valid. Btrfs restore now requires a matching complete single-device dependency and refuses legacy/topology-blind Btrfs partition manifests before starting a writer.
- [ ] Complete Btrfs filesystem-level capture planning, including read-only snapshot consistency/provenance and multi-device/profile dependencies. Btrfs remains a filesystem/block-device image using `partclone.btrfs`; Feclora will not create separate per-subvolume image artifacts. Mounted-filesystem allocation-profile inventory is implemented, and single-device count is recorded/required for restore; unmounted profile discovery, snapshot-assisted capture and coordinated multi-device imaging are not implemented.
- [x] Add a read-only logical-volume restore preflight for an existing LV target: require complete/healthy VG and PV membership, sufficient LV capacity, active and uniquely resolved kernel device identity, no read-only/mounted target, and no snapshot/origin overwrite. Validate thin-pool health and data/metadata percentages; warn that dynamic allocation cannot be reserved by preflight. No activation or writes occur.
- [x] Add a low-level logical-volume capture entry point that requires one active, uniquely inventoried LV in a healthy VG, a known positive LV byte size and a non-hidden, non-snapshot source; it emits the distinct `logical-volume-image` artifact role and uses the existing Partclone/raw stream, source-safety and atomic artifact publication path.
- [x] Add manifest-backed logical-volume image-set orchestration: run the layer-aware capture planner, reject blockers/unknown geometry, capture the LV, optionally encrypt/sign, validate the `logical_volume` manifest and atomically publish artifact/signature/manifest. Unit tests cover successful publication and fail-closed preflight; the local durable-operation API and Cockpit operation wizard now expose LV capture. Deployment-job capture and LV restore remain pending.
- [x] Connect logical-volume restore preflight to a safe LV restore engine and local Cockpit workflow. Restore only into an existing active, unmounted linear or thin LV; verify raw bytes by read-back and Partclone filesystems with a read-only checker. No LVM metadata provisioning/resizing is performed. Deployment-job LV restore is now wired through unicast and multicast Client flows, with local LV selection and fresh inventory preflight. Deployment-job LV capture, opened-mapping restore, LUKS2-on-LV restore, LUKS2 provisioning/rekeying and Btrfs layer-aware restore remain pending. Raw LUKS2 container partition restore now requires explicit encrypted-container provenance, a matching header-included UUID dependency, raw bytes, and post-write cryptsetup UUID/JSON verification; it never opens the mapping. The manifest schema, planner and LV preflight are safety/metadata primitives only; they do not create snapshots, activate storage, or perform writes.
- [x] Add fail-closed raw LUKS2 container partition restore: require `encrypted_container_bytes` + `luks2_container` provenance, a valid manifest UUID and exactly one matching dependency marked included in source bytes; require raw image bytes; retain the closed encrypted container (including its header/keyslots); verify exact raw read-back and then verify the target's LUKS2 UUID/JSON metadata with `cryptsetup` without opening it. Reject opened-mapping plaintext images and inconsistent layer metadata before writing. Local and existing Server/Client partition restore paths use this shared engine. Automated tests cover UUID match/mismatch and mapping rejection. An opt-in disposable loop-device acceptance harness now creates a LUKS2 source, sends the image through Feclora's real unicast control and artifact-transfer protocol over a local socket pair, runs `execute_client_image_job` and restores its raw container to a second loop partition. It verifies wrong-key rejection, opens with the original key and compares plaintext byte-for-byte. The socket pair substitutes for an authenticated TLS stream: live mTLS negotiation and routed network transfer are not covered. Multicast Client dispatch is covered by runtime tests; actual UDPcast/IGMP behavior is covered by the existing two-Client VM operator runbook. The harness has not yet been executed on a real Fedora/Linux host; record OS, kernel, cryptsetup version and exact commit when run.
- [ ] Validate alignment, sector size, geometry and EFI/BIOS/recovery partition roles where a whole-disk restore is planned.
- [ ] Complete capture/restore only for explicitly supported LVM layouts and Btrfs multi-device/profile/snapshot combinations; reject unsupported combinations before writing. LUKS2 raw-container-to-partition restore is implemented; opened-mapping restore, LUKS2-on-LV, provisioning and rekeying are explicitly out of scope until a separate key/provisioning design is approved.
- [ ] Add Cockpit topology views and a read-only capture/restore compatibility preview. Feclora does not create/resize VGs or LVs, manage Btrfs snapshots, format LUKS devices, or otherwise administer those external storage stacks.
Acceptance: inventory accurately identifies VG/LV, Btrfs snapshots and LUKS layers; capture plans state exactly what bytes and metadata are included; unsupported/degraded layouts fail closed before destructive work; successful restores verify the resulting topology and data.

undefined

## P1 — GitHub Pages guides
Publish task-oriented guides only when the exact workflow is implemented; mark future workflows as planned.
1. [x] Local disk-to-disk clone ([published guide](GUIDE-LOCAL-DISK-CLONE.md)).
2. [x] Remote disk-to-disk clone ([operational guide](REMOTE-DISK-CLONE.md)).
3. [ ] Capture disk image to remote SSHFS repository.
4. [ ] Restore image from SSHFS to one disk.
5. [ ] Restore image to multiple remote clients.
6. [ ] Restore multiple clients using PXE. Implemented: the active Server job publishes/revokes a non-secret iPXE handoff; Cockpit exports each enrolled Client's mTLS identity to its own removable medium; the Live image mounts that medium read-only and automatically starts the PXE Client service for unattended boots. The first automatic path supports one Client per unicast whole-disk job, requires a WWN/serial binding, resolves exactly one local disk, and retains Server READY/ARM. Remaining: simultaneous multi-Client/multicast PXE, partition/LV targets, expiry/replay/restart acceptance, Server-side result reconciliation and BIOS/UEFI PXE VMs.
PXE handoff, identity media and the current supported scope are documented in [docs/PXE-UNATTENDED.md](PXE-UNATTENDED.md).

7. [ ] Unattended multi-client PXE restore. The authenticated single-Client path now consumes a dedicated Client mTLS identity, fetches the active authorized job over TLS 1.3 mTLS, resolves one disk using the job's stable WWN/serial binding, runs local preflight, and waits for the explicit Server ARM gate. Boot parameters and job UUIDs alone never authorize writes. Partition restore, multicast unattended execution, interrupted-job/replay acceptance and full operator result reconciliation remain pending.
8. [ ] Initial Server/Client setup, enrollment and trust.
9. [ ] Repository and credential administration.
10. [ ] Storage-layer restore and fidelity: local LV restore and raw LUKS2 container-to-partition restore are implemented; deployment LV acceptance, operator execution of the LUKS2 loop-device and multi-Client multicast runbooks, opened-mapping/LUKS2-on-LV semantics, provisioning/rekeying, and Btrfs snapshot/multi-device support remain pending. No additional LUKS2 implementation work is planned until operator acceptance results identify a concrete defect.
11. [ ] Interrupted-operation and PKI recovery.

The [guide index](GUIDES.md) distinguishes available procedures from planned
workflows. Do not publish an operational recipe for an unimplemented path.
Every guide needs prerequisites, supported layouts, exact Cockpit steps, expected results, verification, failure recovery and data-loss warnings. Use version-matched screenshots or clearly labeled mockups, plus role/network diagrams; mockups are illustrative and not runtime acceptance evidence.

## Operator acceptance guides

- [x] Publish step-by-step operator procedures for physical two-machine clone, multi-Client unicast/multicast restore, SSHFS/NFS/SMB/WebDAV repository checks, interruption/restart recovery and repository lease protection ([ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md)).
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


## SFTP image-set integration checkpoint

A standalone `sftp_image_set.py` publisher validates the v1 manifest,
verifies its minisign signature with an independently trusted public key,
checks each artifact's size and SHA-256, then uploads artifacts, detached
signature and manifest in that order. The manifest is the final visibility
marker; inventory requires its adjacent signature to exist, so readers never
discover a set between the two metadata uploads. A failed transfer may leave
orphan files, but cannot expose an incomplete set through inventory.

- [x] Validate the existing signed manifest and every local artifact before transfer.
- [x] Publish artifact files and detached signature before the manifest commit marker.
- [x] Add unit coverage for ordering, digest mismatch, signature failure and interrupted upload.
- [x] Fetch manifest/signature into a private staging set and enforce metadata size limits.
- [x] Verify downloaded manifest signature before fetching listed artifacts; verify size and SHA-256 for every artifact.
- [x] Integrate SFTP image-set publication with disk/partition capture operations, retaining durable capture-job tracking and requiring signed manifests.
- [x] Integrate authenticated SFTP image selection with durable disk/partition restore jobs, binding the inspected image ID and manifest digest before artifact retrieval.
- [x] Add bounded retries for transient SFTP download and inventory transport failures; never retry uploads automatically when publication outcome may be ambiguous.
- [x] Route SFTP image import and publication through the durable local-operation worker, with Operation log state and orderly cancellation of the transient SFTP child service.
- [x] Persist artifact-boundary progress checkpoints for verified downloads and published uploads.
- [ ] Add continuous byte-level progress within individual files, safe resume semantics, remote orphan discovery/cleanup and complete recovery behavior.
- [x] Expose one-shot SFTP endpoint and encrypted SSH-key/known_hosts credential selection through Cockpit.
- [x] Add reusable saved SFTP endpoint definitions and encrypted credential references.
- [ ] Add provider health checks and multi-directory inventory/discovery.
- [ ] Add operator guide and screenshots or clearly labeled mockups after the complete workflow exists.

SFTP is available in Cockpit for signed-image publication, import and direct disk/partition restore. Named endpoint definitions and encrypted credential references are saved in a root-owned registry. Remote manifest-marker inventory, signed-image import and publication are submitted as durable local operations and can be cancelled from the Operation log. Import/publication progress is checkpointed at artifact boundaries; continuous byte-level progress within a file and resume are still missing. Transient read-only downloads and inventory retry connection faults up to twice; uploads are not automatically retried. Unit tests exist; live provider acceptance remains outstanding.


### SFTP authenticated image-set retrieval checkpoint

The standalone fetch primitive downloads manifest and detached signature into
a private staging directory without treating either as trusted. It checks
metadata size limits, validates manifest v1 and verifies minisign against an
independently trusted public key before requesting artifacts. Each artifact
download is checked against the signed SHA-256 and byte count. It then imports
artifacts into the native flat Feclora repository layout, publishes the
signature, and publishes `<image_id>.manifest.json` last using no-overwrite
hard links. This matches the current Cockpit inventory/restore filename
contract. It is manifest-last multi-file publication, not one atomic
transaction; on a collision, files created by the attempt are removed and
pre-existing files are preserved.

- [x] Add restricted transient-service mode for unverified manifest/signature downloads.
- [x] Verify signed manifest before downloading any image artifacts.
- [x] Download and verify every artifact against signed size and SHA-256.
- [x] Import verified files into the native local image repository, with signature and manifest published last and no-overwrite hard links.
- [x] Test metadata-first ordering, bad signature rejection, digest mismatch, collision refusal, staging cleanup and rejection of artifact names in the native manifest-marker namespace.
- [x] Add safe Cockpit remote manifest-marker listing and authenticated signed-manifest metadata inspection before artifact retrieval; multi-directory catalog discovery remains pending.
- [x] Connect authenticated SFTP fetch/import to a journaled Cockpit API action and local image inventory.
- [x] Connect signed-image publication to disk/partition capture and existing Cockpit upload actions.
- [x] Add bounded retries for transient SFTP download and inventory transport failures; never retry uploads automatically when publication outcome may be ambiguous.
- [ ] Add transfer byte progress, operator cancellation, resume and complete recovery semantics.
- [x] Expose one-shot Cockpit SFTP image import and signed-image publication forms with encrypted SSH-key/known_hosts selection and local signing trust.
- [x] Add a private root-owned registry and Cockpit save/select/remove controls for named SFTP endpoints with encrypted credential references.
- [ ] Add multi-directory inventory/discovery and provider health checks.
- [x] Add a Cockpit/API action to publish an existing locally signed image set to SFTP, verifying the local minisign signature and artifact digests before upload.
- [x] Add optional automatic SFTP publication to durable disk/partition capture jobs, requiring a signed manifest and registered encrypted SSH-key/known_hosts credentials.
- [x] Integrate authenticated SFTP image selection with durable disk/partition restore jobs; bind the requested image ID and inspected manifest SHA-256 to the signed remote manifest, then verify all artifacts before destructive restore starts.
- [ ] Implement continuous byte-level progress within files, safe resume and full provider acceptance for SFTP-backed restore jobs. Restore fetches already run in the durable worker with cancellation and artifact-boundary progress; bounded retry for transient read-only transfers is already implemented.
- [ ] Add operational guide and version-matched screenshots or clearly labeled mockups after Cockpit workflow acceptance.

Automated tests are present; check CI for the exact commit before reporting a passing result. Cockpit can preview remote image metadata only after verifying the detached minisign signature against the configured independent trust key. Both explicit import and direct restore fetch artifact content and verify signed sizes and SHA-256 values before the image is made available to the restore engine. SFTP publication is also integrated with manual Cockpit upload and optional post-capture publication. This is not yet a complete reusable SFTP provider: inventory is limited to one configured directory; the underlying SFTP child transfers are synchronous, while image import/publication are queued as durable cancellable operations with artifact-boundary progress. Continuous byte-level progress within a file, safe resume and multi-directory catalog discovery remain pending. Bounded retries apply only to transient read-only transport failures.
