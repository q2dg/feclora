# Feclora completion plan

This document is the dependency-ordered implementation backlog and acceptance contract. It complements ROADMAP.md and FEATURE-MATRIX.md.


## Product target: Fedora Server minimal Live kiosk with six Cockpit workflows

The maintainer's end-user requirements and measurable release gates are defined in [USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.md). The target workflows cover local and remote disk/partition cloning, image capture to SSHFS/NFS/SMB or S3, single-target restore, multi-Client restore and unattended PXE. S3 is an object-storage repository using an HTTPS API, not a mounted filesystem. The Live image uses a minimal Fedora Server userspace; Cage launches Firefox in kiosk mode against the local Cockpit endpoint.

Do not mark a workflow complete because an engine, command builder, protocol primitive or operator acceptance recipe exists. Completion requires an end-to-end Cockpit path, backend/runtime integration, safe authorization and failure handling, progress/results, automated software tests and a matching published step-by-step guide. Operator acceptance procedures may be documented, but physical hardware, network and live-service execution are optional and outside this software completion gate. The PXE answer path downloads and validates JSON in Live, resolves the repository ID through the Live client's normal SSHFS, NFS, SMB/CIFS or S3 manager, and restores through the existing engine with stable-target revalidation. Repository credentials remain in the protected Live configuration; the PXE Server serves boot assets and answer JSON only and receives no restore results. Remaining PXE software work is automated failure-path coverage (including passphrase, revocation and repository errors); physical/network acceptance is optional and outside the software completion gate. The standalone signed restore-profile executor is separate from this PXE answer workflow.

## Explicit follow-up queue (do not drop)

This short list keeps the remaining cross-cutting work visible; the detailed acceptance criteria below remain authoritative.

1. **Close unattended PXE:** obtain clean static/unit CI for the exact commit and complete automated failure-path coverage for wrong passphrases, answer revocation and SSHFS/NFS/SMB/S3 repository errors. ISO/PXE physical and network boot checks are optional operator acceptance, not software completion gates. The Live client uses its normal protected repository configuration; do not add credentials to the answer or result reporting to the PXE Server. See [PXE design and acceptance](PXE-UNATTENDED.md).
2. **Btrfs remains unfinished:** unmounted root-tree inspection and subvolume ancestry/provenance discovery are implemented without mounting filesystems. Allocation-profile discovery is still limited to mounted filesystems; snapshot-consistent capture, coordinated multi-device/profile imaging and layer-aware restore remain unimplemented. Do not silently flatten a multi-device filesystem or claim consistent capture from a mounted/in-use source. See **P1 — Storage discovery and image fidelity** below.
3. **Finish repository providers and lifecycle:** complete automated SSHFS/NFS/SMB failure, root-squash, stale-mount, interruption, concurrency and cleanup coverage. S3 object API, encrypted credentials, multipart cleanup, manifest-last publication and distributed capture/restore are implemented; live-provider acceptance is optional. See **P0 — Remote repositories and credentials** below.
4. **Close storage-layer gaps:** LUKS2-on-LV and opened-mapping restore, snapshot-assisted LVM/Btrfs capture, and the remaining layer-aware Btrfs/LUKS2 restore paths. Keep provisioning/rekeying and unsupported plaintext mapping restores explicitly out of scope unless separately specified.
5. **Complete fleet and release engineering:** automated two-peer integration tests with disposable image-backed devices, protocol/fault-injection coverage, durable worker supervision, byte-level progress/throughput reporting, operation-history export, reproducible frontend builds and security/dependency checks. Real Fedora Live, hardware, network-switch and live-provider runs are optional operator activities.
6. **Implement the additional operator-requested workflows end to end:**
   - **Physical-device multicast:** add a distinct Server-to-many-Clients block-device streaming operation over UDPcast. Keep the source read-only and identity-pinned; every Client must independently select and type-confirm its destination, validate device class/capacity/sector geometry, and verify destination read-back against a source digest/transfer metadata delivered over the existing control channel. Do not route this through the image-artifact staging/restore path. Preserve the configurable READY-client threshold/deadline and explicit Server start gate.
   - **P2V:** Cockpit wizard and durable local-operation lifecycle now invoke the source-safe `qemu-img` conversion engine, stage privately, verify QCOW2 metadata and publish a `.qcow2` file plus `.p2v.json` sidecar to local/SSHFS/NFS/SMB filesystem repositories. Remaining: S3 object publication, first-class QCOW2 catalog/inventory and Fedora Live validation; exact-commit Python tests and static checks pass. Do not silently modify the physical source or promise that conversion alone makes every OS bootable.
   - **Self-contained recovery ISO:** the `recovery_iso.py` engine validates the Live base El Torito catalog, manifest and every artifact size/SHA-256, strict target-bound restore answer, output capacity and no-overwrite publication; xorriso replays the source boot catalog and embeds the image set under `/FECLORA/RECOVERY`. A Cockpit wizard now submits a durable worker operation, selects a whole-disk image from local or mounted filesystem repositories, requires a local base ISO path and WWN and/or serial target selector, and publishes a separate `<image_id>.recovery.iso`; S3 output is rejected. Remaining: Live boot-time discovery of the embedded read-only image repository, restore dispatch through the existing safe restore engine, real xorriso assembly and BIOS/UEFI acceptance. Never embed credentials or age passphrases; keep generic PXE answer publication separate. Do not build an ISO in CI or during repository work.
   - **Locale and keyboard:** add independent UI selectors for the requested languages and keyboard layouts, real translations rather than relabeling English, and safe application of the selected locale/keymap in the Live session. Keep the defaults configurable and do not infer the keyboard solely from language.
   - **Remote start policy:** Cockpit controls, job validation, coordinator/service enforcement and READY-only dispatch now support manual, minimum READY-client count and UTC deadline gates. Exact-commit Python tests and static checks pass; multi-peer acceptance remains pending. The PXE MAC-admission limit is a separate mechanism.
   - **Remote terminal actions:** Cockpit exposes no action/reboot/poweroff for remote restore, remote clone and image multicast restore. Client service reports its successful write/read-back result before invoking a fixed systemctl action; failed/interrupted Clients remain powered on. Exact-commit Python tests and static checks pass; physical power-state acceptance remains pending. Extend to physical-device multicast when that workflow lands.
   - **Multi-Client remote clone:** sequential unicast fan-out from one Server source to multiple READY Clients is now wired through the persistent service and Cockpit. Each Client independently approves its destination and verifies read-back. Multi-Client tests pass in CI on the current main commit; two-host fault-injection acceptance remains pending. This is not physical-device multicast.
   - **Pre-capture filesystem checks:** add an explicit, read-only pre-capture check screen where the filesystem supports a non-destructive checker; never run a repair automatically or check mounted/in-use filesystems.


Do not mark end-to-end software paths complete from isolated unit tests alone; retain automated integration and fault-injection coverage. Keep optional operator acceptance records separate from software release gates.

## Delivery principles
1. Reuse established tools and libraries; do not reimplement storage protocols.
2. A feature is complete only when runtime, privileged API, Cockpit workflow, failure handling, automated tests and documentation agree.
3. Destructive operations fail closed, require explicit authorization and verify results.
4. Never persist passwords, private keys or `age` identities in profiles, journals, logs or browser storage. Age encryption is optional; artifact integrity is checked with SHA-256 and repository/transport trust controls access to manifests.
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
- [x] Reuse the existing Server-authenticated TLS control session, job-scoped MAC selection, local device approvals, service locks, durable job records and Cockpit status plumbing.
- [x] Keep the direct block-stream data plane separate from UDPcast: the current UDPcast wrapper transfers image artifacts to private staging files for multicast restore; it does not implement direct block-device cloning.
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
- [x] Make age identity/recipient provisioning optional for baseline enrollment, renewal and deployment. TLS-only enrollment/renewal accepts no age material; renewal does not create an age identity when none is configured. 
- [x] Remove manifest signing and signature verification from capture, restore, unicast and multicast workflows. Manifests travel over the authenticated control/SSH transport; artifact integrity is verified with SHA-256. Age decryption is required only for artifacts marked age-encrypted.
- [x] Replace signed standalone restore-profile authorization with a root-owned mode-0600 profile in a root-owned, non-group/other-writable directory, plus expiry, single-use consumption and target identity checks. This local profile mechanism is separate from PXE answer admission.
- [x] Remove image-manifest signing and key management entirely; retain age recipient/identity rotation separately from TLS PKI.
- [ ] Expose preflight, per-client status, expiry, progress and rollback in Cockpit.
- [ ] Test mixed-version clients, interrupted rotation, expiry, wrong SAN/fingerprint and lost Server state.
Acceptance: certificate enrollment, renewal, trust and revocation remain auditable; private material never enters logs/browser state.

## P0 — Remote repositories and credentials
Repository-related abstractions/tests already exist; inspect and extend them rather than creating a second implementation. Architectural boundary: every SSH/ NFS, SMB/CIFS and S3 service, and every  subsystem/namespace, is external and independently administered. Feclora implements client-side connection, credential handling, mount/transfer, integrity, lifecycle of its own client processes, and failure reporting only; it does not deploy or configure remote servers, exports, shares, buckets or  subsystems.
- [x] Inventory current repository code and reconcile the feature matrix.
- [x] Define a provider interface independent of transport.
- [x] Add root-managed SSHFS/NFS/SMB mount lifecycle and Cockpit actions; keep this separate from image-engine integration.
- [x] Report mounted state separately from verified provider/source/type/access-mode identity in Cockpit.
- [ ] Close remaining SSHFS/NFS/SMB software gaps: safe behavior after actual operation I/O errors, interrupted capture/publication cleanup, permission semantics and end-to-end automated Cockpit capture/restore tests. Concurrent publishers are out of scope; retain manifest-last no-overwrite publication without adding a publisher-concurrency protocol. Mount inspection now reports `unmounted`, `mounted_unverified`, `identity_verified` or `unknown`, with remote `health_state=unknown`; bounded findmnt metadata is never interpreted as connectivity. Inspection does not issue stat/statvfs, path lookup, directory listing or other remote I/O. A findmnt timeout/malformed record fails closed and is not translated into unmounted. No automatic unmount/recovery occurs on a suspected outage or identity mismatch. Preserve NFS root-squash/ownership checks.
  - Partial progress: after a successful mount-helper exit, a verification failure triggers best-effort rollback only while `findmnt` still proves the exact configured provider/source identity; a non-zero helper exit is never treated as proof of mount ownership, so any appearing mount is left untouched for inspection. Rollback uses normal `umount` only and never force/lazy detach. NFS unmount separately retries with `umount --force` only after the exclusive repository-use lease is acquired and a normal unmount fails; SSHFS/SMB are never force-detached. Automated failure-injection tests cover matching partial mounts, restrictive-option verification failure, and the no-force policy. The read-only inspection path now distinguishes unmounted, mounted-but-unverified, identity-verified and unknown states; it never performs remote filesystem I/O and always reports remote health as unknown. A findmnt timeout is not interpreted as unmounted, and no automatic stale-mount detach is attempted. Actual I/O-error handling and live outage recovery remain open.
  - All managed SSHFS/NFS/SMB mount commands request `nosuid,nodev,noexec`; repository resolution now also verifies that all three flags are present in the active mount options, so an externally replaced or weakened mount is never trusted for image operations. Unit tests cover a missing flag. Live helper/kernel compatibility remains part of provider acceptance.
  - Added an automated root-squash regression test: a manifest whose NFS-visible owner is the anonymous UID is rejected by the existing root-owned regular-file check. This deliberately preserves the trust boundary; NFS exports must provide compatible ownership for Feclora-managed manifests.
  - Added a shared manifest-last publisher for whole-disk, partition and logical-volume image sets. It pins the repository/staging directory inodes, verifies the staging directory is a direct child of the repository, and rolls back only final links whose inode still matches the staged file. A concurrent replacement is never unlinked during rollback; tests cover collision rollback and this replacement race. This protects per-attempt publication integrity but does not yet provide a cross-host single-publisher lease or stale staging-directory janitor.
  - Capture artifact publication now rolls back the final hard link if the repository-directory sync fails, but only when the final name still refers to the exact inode created by that capture. This avoids leaving a visible artifact after reporting capture failure and never unlinks a concurrent replacement; staging cleanup remains private to the attempt.
  - The low-level artifact writer now applies the same inode-ownership rule when rolling back a final hard link after staging-name cleanup or directory-sync failure. If another actor has replaced the final name, rollback preserves that replacement instead of unlinking by filename alone. A failure-injection regression test covers the staging-unlink race.
  - Cockpit image operations hold a shared per-repository usage lease for the full capture/restore/verification/extraction context. Remote SSHFS/NFS/SMB and S3 inventory now also acquire a shared lease before scanning manifests or listing objects and release it on both success and failure. Remote filesystem inventory now propagates directory/stat/read I/O failures instead of silently returning a partial or empty result; missing local image directories retain the existing empty-inventory behavior. Unmount, update and removal require the exclusive lease; tests cover inventory lease retention/release and cross-process lock exclusion. Publication remains manifest-last with no-overwrite atomic links; no remote free-space or I/O health probe is performed because hard-mounted NFS probes can block indefinitely.
- [ ] Complete safe  per-repository credential isolation and provider lifecycle; do not depend on the global  secrets file. Keep the provider unavailable until isolated credentials and HTTPS certificate validation are tested.
- [x] Add optional repository-ID routing for whole-disk/partition capture, restore and partition extraction; resolve only mounted, verified repositories and enforce read-only mounts for writes. Local repository remains the backward-compatible default.
- [x] Expose repository selection and per-repository image inventory in Cockpit; route capture, restore, verification, layout inspection and partition extraction to the selected verified mount.
- Optional operator acceptance (documented in `ACCEPTANCE-TESTS.md`): SSHFS, NFS and SMB/CIFS checks against real services, including permissions, root-squash, disconnects and interrupted capture/restore. These checks are explicitly not required for software-backlog completion.
- [x] Store repository credential references as host-bound encrypted systemd credential blobs under root-only storage; never persist plaintext in ordinary config/logs.
- [x] Validate referenced secret files through `O_NOFOLLOW` descriptors and `fstat`; reject symlinks, unsafe ownership/modes and hard-linked credential files.
- [x] Enforce SSH host-key pinning with strict checking and a selected `known_hosts` reference; expose encrypted SSH key/known-hosts selection in Cockpit and validate ownership, mode, link count and symlink safety. Encrypted credential replacement is available; live rotation/reconnect acceptance remains pending.
- [x] Add the root-only credential-store primitive and Cockpit import/removal of protected local source files into host-bound systemd-creds blobs; Cockpit lists metadata and preserves references when removal is attempted. Full credential rotation/recovery acceptance remains pending.
- [x] Add an initial systemd-creds-backed encrypted credential store and transient per-repository mount services using `LoadCredentialEncrypted=` for SSHFS and SMB. The mount helper consumes credentials only from `$CREDENTIALS_DIRECTORY`; encrypted  references are explicitly rejected because root-invoked  uses the global secrets file.
- [x] Add a local root-only credential import/removal CLI that reads protected source files, plus a read-only Cockpit API inventory of validated credential references; the API never accepts or returns secret material.
- [ ] Integrate Fedora `oo7-daemon` Secret Service with interactive operator-session workflows where a user bus is available; never make unattended Server jobs depend on that session.
- [ ] Design and implement a safe per-repository  credential lifecycle compatible with 's root-mount semantics; do not use or mutate the global `/etc//secrets` as a multi-repository workaround. Extend encrypted service credentials to other long-running Server jobs; migrate existing plaintext credential references and remove the legacy plaintext store/CLI only after compatibility and recovery paths are covered.
- [x] Add Cockpit import/removal of protected local credential files into systemd-creds storage, read-only encrypted-reference inventory, and credential selection for SSHFS and SMB repositories.
- [x] Add Cockpit repository definition editing while unmounted, explicit mount-identity inspection (findmnt source/type/access-mode comparison only; not a live health or I/O probe), and safe reference-preserving credential removal.
- [x] Serialize repository registry add/update/remove transactions across processes with a private root-owned lock; reload the registry under lock, cover concurrent adds, symlinked-lock rejection and failed-removal rollback with unit tests.
- [ ] Add safe  per-repository encrypted credentials and isolated  service configuration; and automated mount-lifecycle coverage. is rejected by validation and is not a supported managed provider today.
- [ ] Complete stale-mount recovery after network loss, interrupted publication cleanup and provider I/O-error handling. Concurrent read/restore access to committed images is covered by shared leases; concurrent publishers for the same image remain out of scope.
- [ ] Add integration tests with local test services where practical.
Acceptance: engines use repository IDs/handles, secrets are redacted, failures cannot leave falsely complete images.

## P0 — Durable operations and progress
Existing foundation: deployment journals, persistent Server service lifecycle, root-only Unix-socket control, Client progress and local operation log. Architecture decision: [ADR 0010](adr/0010-durable-local-operations.md).
- [x] Define a versioned local-operation state machine and hash-chained event schema without changing existing deployment journals.
- [x] Move local long-running capture/restore/clone work out of the Cockpit/API request process into a root-owned systemd worker independent of UI sessions.
- [x] Make Cockpit submit validated jobs and consume durable operation IDs, status and progress; browser disconnection does not own worker execution.
- [x] Persist queued, preflight, running, verifying, completed, failed and interrupted states; active destructive writes are deliberately non-cancellable.
- [x] Persist monotonic elapsed time and sampled bytes/second with local byte-progress checkpoints when consecutive counters are comparable; omit the rate for the first sample or after a counter reset.
- [ ] Report bytes, phase, throughput, timestamps and bounded diagnostic categories consistently across every local operation; standardize phase and diagnostic categories across all operation engines.
  - The durable journal boundary normalizes incoming progress phases to a fixed vocabulary and accepts only bounded diagnostic categories; engines still need to emit meaningful phase/category values. Server-side artifact-transfer progress is implemented through the Server sender callback and existing journal.
  - Worker failures now persist a bounded diagnostic category derived from errno/exception type (permission, capacity, device, network, credentials, integrity, unsupported, or internal); raw error text remains separately length-limited. Operation-specific default phases are now assigned when engines omit a phase; finer-grained engine phase emission remains outstanding. Server-side artifact-transfer progress is emitted by the Server sender and persisted through the existing journal.
- [x] Detect unfinished local operations across reboot and mark them interrupted for manual review; never resume destructive I/O automatically. Verify and harden detached-worker supervision on live systemd hosts.
- [x] Add process-independent per-device locks/conflict detection while preserving the existing host-wide storage/deployment exclusion.
- [x] Expose local operation history and event detail in Cockpit, including JSON export of the latest 100 loaded operations; richer filtering remains pending.
- [x] Add Server-side artifact-transfer progress using the Server sender's local callback and existing journal; do not inject progress frames into the TLS artifact stream.
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

## P1 — Smaller-destination cloning and restore

A smaller destination must not be enabled by weakening the existing raw-copy capacity checks. The current whole-disk clone copies the source byte range verbatim, and whole-disk restore writes a raw disk artifact; neither operation can safely fit a smaller target by truncation.

Implementation contract for a future proportional-layout mode:

- [ ] Keep the current exact/raw mode unchanged and fail closed when the destination is smaller.
- [ ] Add a separate, explicit proportional-layout mode; never silently resize.
- [x] Add read-only whole-disk source discovery using `lsblk`, `blockdev` and `sfdisk`; require an offline/unused whole disk, GPT, matching logical-sector geometry and exact agreement between the discovered partition set. Validate ordered/non-overlapping partition extents, device nodes and GUIDs, and require sfdisk's first/last usable LBAs to fit the actual disk capacity and contain every partition. The source's protective MBR, primary/backup GPT headers, header CRCs, entry-array CRCs, disk GUID, usable-LBA bounds and partition records are independently read from the block device and cross-checked against sfdisk. Destination-side binary inspection remains pending.
- [x] Add a preview-only GPT layout planner that validates ordered/non-overlapping source partitions, GPT type GUIDs, target capacity and caller-supplied minimum sizes. It preserves every source partition start and identifier; it never relocates or repacks partitions. It may shorten only the final ext2/3/4 or NTFS partition, and only when its filesystem-native probed minimum fits before the target backup GPT metadata. Other filesystems retain exact original size; unknown filesystems/storage layers fail closed. Earlier partitions that cross the target boundary, or a final unsupported partition that crosses it, are rejected. This is intentionally narrower than a general proportional resize, but avoids an unimplemented data-relocation algorithm.
- [x] Integrate trusted offline filesystem-minimum probes into a read-only source-to-smaller-target preview API; no write authorization is returned. Reject extended/logical MBR layouts or other schemes until their handling is implemented and tested.
- [x] Add read-only ext2/3/4 and NTFS minimum-size probes: ext verifies the detected type, runs `e2fsck -f -n`, reads the ext block size and `resize2fs -P` estimate; NTFS verifies the detected type and runs `ntfsresize --info` (read-only). Both bound the estimate by block-device capacity and refuse mounted/busy/root-backed sources through the existing source-safety checks. Estimates remain advisory; the staged shrink must independently succeed and be checked.
- [x] Add a read-only probe-backed planner adapter and connect it to automatic source discovery: ext2/3/4 partitions use the offline `resize2fs -P` probe and NTFS/ntfs3 partitions use the offline `ntfsresize --info` read-only probe; other known filesystems remain fixed at their exact original size; unknown signatures and probe failures abort planning. Never infer fit from free-space percentages or lsblk partition size alone. The preview API is not connected to an end-user clone/restore executor.
- [ ] Initially support only filesystems with a proven offline shrink-and-grow sequence and verified tool availability. Filesystems without a safe shrink path, encrypted/container layers, RAID, LVM, multi-device Btrfs and unknown signatures must remain blocked.
- [ ] Build a private working image from the verified source artifact; never shrink or otherwise modify the original source disk or repository artifact. Shrink the staged final ext2/3/4 or NTFS filesystem offline, run a mutating consistency check only on the private copy, and verify the resulting filesystem size before changing its partition boundary. Do not proceed if the staged copy cannot be isolated and bounded.
- [ ] Write the reduced GPT only into the private working image, regenerate and validate primary/backup GPT metadata and CRCs, then copy the complete transformed image to the destination under a fresh identity/capacity/offline check and exact typed confirmation. Read back and verify the written byte range, GPT geometry and the restored ext/NTFS filesystem. No source or destination mutation is allowed before the complete private image passes validation.
- [ ] Verify the resulting partition table, filesystem consistency and byte/data integrity before reporting success. An interrupted operation must leave the target explicitly untrusted.
- [ ] Add disposable loop-device integration tests for exact-fit, insufficient-used-space, unsupported filesystem, GPT relocation, alignment, cancellation and failures at every destructive stage.
- [ ] Expose the mode in local and Cockpit workflows only after the same engine and validation contract are integrated end to end.

Until those gates pass, a smaller target is **not supported**. The UI may explain that proportional resizing is a future mode, but must not offer a “continue anyway” action for a raw clone or restore.

## P1 — Storage discovery and image fidelity
Scope clarification: LVM logical volumes, LUKS2 containers/open mappings, Btrfs filesystems and Stratis-backed devices are storage source layers/types to inventory and image, not repository or transport types. Repositories/transports are the separate external destinations and distribution mechanisms (SSHFS, NFS, SMB/CIFS and S3;  remains a separate block transport). This is an image-creation and restore-compatibility requirement, not a request for Feclora to administer storage stacks or provision them. Feclora must discover and describe existing layers accurately, then capture the selected block-level or filesystem-level content without silently flattening or omitting them.
Existing foundation: block inventory, read-only LVM reporting, Btrfs/Stratis inventory, restore profiles and whole-disk layout preview.
- [x] Add a conservative read-only storage graph joining lsblk disk/partition ancestry, LUKS2 containers and active crypt mappings, exact-path LVM PV/VG/LV relationships, filesystem signatures, Btrfs multi-device membership and discovered subvolume/snapshot provenance. Unmatched aliases and missing devices are reported as unresolved; no path aliases or ancestry are guessed.
- [x] Extend the graph with Btrfs mount-source UUID linkage, Btrfs filesystem-to-subvolume membership and Stratis pool/filesystem/backing-device membership. Mount UUIDs and Stratis device paths are joined only when exact inventory evidence matches; unmatched paths remain unresolved.
- [x] Resolve LVM LV aliases to lsblk block devices using the active kernel major/minor identity reported by LVM and lsblk. A major/minor match must be unique; ambiguous or unavailable identities remain unresolved, and even an exact path match is rejected if both reported major/minor identities conflict. Link matched LVs to discovered filesystem nodes without relying on mapper path spelling.
- [x] Extend read-only LVM reports with PV/VG/LV membership, physical/free extents, thin-pool and snapshot indicators, missing-PV counts/attributes, and LV health summaries. Preserve raw LVM rows and report degraded or unknown VG health conservatively. Automated tests added; Fedora 45 runtime compatibility and real missing-PV/thin-pool fixtures still require validation.
- [x] Discover subvolumes on already-mounted Btrfs filesystems and distinguish snapshots from ordinary subvolumes using parent UUID metadata; record received UUID provenance separately without assuming every received subvolume is a snapshot.
- [x] Extend read-only Btrfs inventory for already-mounted filesystems with Data/Metadata/System/GlobalReserve allocation profiles, preserving unknown profile names rather than normalizing them to a supported mode. Attach profile observations to the storage graph; do not mount or modify filesystems.
- [x] Inspect unmounted Btrfs root trees without mounting: collect current subvolume IDs/generations/used bytes, read-only flags, UUID/parent UUID/received UUID provenance, and ROOT_BACKREF parent IDs/names; resolve paths only when ancestry is unambiguous. Multi-device membership remains tied to the complete device set reported by filesystem show.
- [x] Inspect unmounted Btrfs chunk trees to report Data/Metadata/System allocation profiles, logical chunk lengths, stripe counts and device IDs/offsets; attach chunk-to-device and subvolume/snapshot relationships to the storage graph. Offline used-byte accounting remains explicitly unknown.
- [ ] Validate snapshot consistency and implement coordinated multi-device/profile capture; mounted Data/Metadata/System/GlobalReserve used-byte observations remain available, but no coordinated snapshot capture or multi-device imaging is implemented.
- [x] Tag LUKS container signatures and active `crypt` device-mapper mappings in the read-only `lsblk` inventory; no passphrases are requested or stored.
- [x] Inspect LUKS2 headers read-only with `cryptsetup`: UUID, cipher, sector size where available, and keyslot/token/segment counts. Do not expose token payloads or request/store passphrases.
- [x] Distinguish raw LUKS2 container bytes (including header/keyslots) from plaintext bytes read through an opened crypt mapping in capture planning; nested LUKS containers do not change a whole-disk image's byte scope. Never request or persist passphrases in ordinary profiles, logs or browser state.
- [ ] Represent unknown, degraded, missing and unsupported layers explicitly; never present discovery as proof that capture or restore is supported.
- [x] Connect the layer-aware capture planner to the Cockpit partition-image capture path. Raw LUKS2 partition images are stored as encrypted-container bytes only after `cryptsetup` verifies a version-2 header (including headers/keyslots, never passphrases); LUKS1 and unknown headers fail closed with LUKS UUID provenance; supported single-device Btrfs partition images record filesystem UUID/dependency provenance and continue to use `partclone.btrfs`. Incomplete multi-device Btrfs selections fail closed.
- [x] Extend Btrfs capture preflight to require complete member-device and chunk-stripe mappings, known allocation profiles and verified mount state; reject mounted Btrfs filesystems and unknown profiles before imaging. No snapshots are created.
- [x] Add a read-only capture planner for whole-disk, partition and logical-volume byte scope; distinguish raw LUKS2 containers from opened crypt mappings; report nested LUKS/LVM dependencies; check LV/VG metadata dependencies and multi-device Btrfs completeness; block mounted/in-use sources. The planner is a safety/metadata primitive only; it does not execute capture or create snapshots.
- [x] Extend image manifests with a distinct logical-volume image type/artifact role and strictly validated storage metadata for byte scope, LUKS2 UUID, LVM VG/LV identity, Btrfs filesystem/subvolume provenance, Btrfs device count and explicit dependency identities. Capture planning emits portable LVM/LUKS metadata; older disk/partition manifests remain valid. Btrfs restore now requires a matching complete single-device dependency and refuses legacy/topology-blind Btrfs partition manifests before starting a writer.
- [ ] Implement snapshot-assisted Btrfs capture and coordinated multi-device/profile image sets with layer-aware restore. Btrfs remains a filesystem/block-device image using `partclone.btrfs`; Feclora will not create separate per-subvolume image artifacts. Unmounted subvolume ancestry and chunk profiles/stripe dependencies are inventoried, and the planner blocks mounted, incomplete or unknown-profile sources; it does not create snapshots or image multi-device sets.
- [x] Add a read-only logical-volume restore preflight for an existing LV target: require complete/healthy VG and PV membership, sufficient LV capacity, active and uniquely resolved kernel device identity, no read-only/mounted target, and no snapshot/origin overwrite. Validate thin-pool health and data/metadata percentages; warn that dynamic allocation cannot be reserved by preflight. No activation or writes occur.
- [x] Add a low-level logical-volume capture entry point that requires one active, uniquely inventoried LV in a healthy VG, a known positive LV byte size and a non-hidden, non-snapshot source; it emits the distinct `logical-volume-image` artifact role and uses the existing Partclone/raw stream, source-safety and atomic artifact publication path.
- [x] Add manifest-backed logical-volume image-set orchestration: run the layer-aware capture planner, reject blockers/unknown geometry, capture the LV, optionally encrypt, validate the `logical_volume` manifest and atomically publish artifact/manifest. Unit tests cover successful publication and fail-closed preflight; the local durable-operation API and Cockpit operation wizard expose LV capture. Deployment-job LV capture and restore are implemented through unicast Client flows with local target selection and fresh topology preflight; automated tests cover capture dispatch and manifest-type binding. Multicast LV restore remains implemented. Hardware acceptance is optional.
- [x] Connect logical-volume restore preflight to a safe LV restore engine and local Cockpit workflow. Restore only into an existing active, unmounted linear or thin LV; verify raw bytes by read-back and Partclone filesystems with a read-only checker. No LVM metadata provisioning/resizing is performed. Deployment-job LV restore is now wired through unicast and multicast Client flows, with local LV selection and fresh inventory preflight. Opened-mapping restore, LUKS2-on-LV restore, LUKS2 provisioning/rekeying and Btrfs layer-aware restore remain pending; deployment-job LV capture is implemented. Raw LUKS2 container partition restore now requires explicit encrypted-container provenance, a matching header-included UUID dependency, raw bytes, and post-write cryptsetup UUID/JSON verification; it never opens the mapping. The manifest schema, planner and LV preflight are safety/metadata primitives only; they do not create snapshots, activate storage, or perform writes.
- [x] Add fail-closed raw LUKS2 container partition restore: require `encrypted_container_bytes` + `luks2_container` provenance, a valid manifest UUID and exactly one matching dependency marked included in source bytes; require raw image bytes; retain the closed encrypted container (including its header/keyslots); verify exact raw read-back and then verify the target's LUKS2 UUID/JSON metadata with `cryptsetup` without opening it. Reject opened-mapping plaintext images and inconsistent layer metadata before writing. Local and existing Server/Client partition restore paths use this shared engine. Automated tests cover UUID match/mismatch and mapping rejection. An opt-in disposable loop-device acceptance harness now creates a LUKS2 source, sends the image through Feclora's real unicast control and artifact-transfer protocol over a local socket pair, runs `execute_client_image_job` and restores its raw container to a second loop partition. It verifies wrong-key rejection, opens with the original key and compares plaintext byte-for-byte. The socket pair substitutes for an TLS stream: live Server-authenticated TLS negotiation and routed network transfer are not covered. Multicast Client dispatch is covered by runtime tests; actual UDPcast/IGMP behavior is covered by the existing two-Client VM operator runbook. The harness has not yet been executed on a real Fedora/Linux host; record OS, kernel, cryptsetup version and exact commit when run.
- [ ] Validate alignment, sector size, geometry and EFI/BIOS/recovery partition roles where a whole-disk restore is planned.
- [ ] Complete capture/restore only for explicitly supported LVM layouts and Btrfs multi-device/profile/snapshot combinations; reject unsupported combinations before writing. LUKS2 raw-container-to-partition restore is implemented; opened-mapping restore, LUKS2-on-LV, provisioning and rekeying are explicitly out of scope until a separate key/provisioning design is approved.
- [ ] Add Cockpit topology views and a read-only capture/restore compatibility preview. Feclora does not create/resize VGs or LVs, manage Btrfs snapshots, format LUKS devices, or otherwise administer those external storage stacks.
Acceptance: inventory accurately identifies VG/LV, Btrfs snapshots and LUKS layers; capture plans state exactly what bytes and metadata are included; unsupported/degraded layouts fail closed before destructive work; successful restores verify the resulting topology and data.


## P1 — GitHub Pages guides
Publish task-oriented guides only when the exact workflow is implemented; mark future workflows as planned.
1. [x] Local disk-to-disk clone ([published guide](GUIDE-LOCAL-DISK-CLONE.md)).
2. [x] Remote disk-to-disk and partition-to-partition clone ([operational guide](REMOTE-DISK-CLONE.md)).
3. [ ] Capture disk image to remote SSHFS repository.
4. [ ] Restore image from SSHFS to one disk.
5. [ ] Restore image to multiple remote clients.
6. [ ] Restore multiple clients using PXE. Implemented: the active Server job publishes/revokes a non-secret iPXE handoff; Cockpit exports each job UUID and operational target selection to the Live handoff; the Live image mounts that medium read-only and automatically starts the PXE Client service for unattended boots. The first automatic path supports one Client per unicast whole-disk job, requires a WWN/serial binding, resolves exactly one local disk, and retains Server READY/ARM. Remaining: simultaneous multi-Client/multicast PXE, partition/LV targets, Server-side result reconciliation and BIOS/UEFI PXE VMs.
PXE handoff, identity media and the current supported scope are documented in [docs/PXE-UNATTENDED.md](PXE-UNATTENDED.md).

7. [ ] Unattended multi-client PXE restore. The Server-authenticated single-Client path now consumes a job UUID and selected MAC, fetches the active job over Server-authenticated TLS, resolves one disk using the job's stable WWN/serial binding, runs local preflight, and waits for the explicit Server ARM gate. Boot parameters and job UUIDs alone never authorize writes. Partition restore, multicast unattended execution, and full operator result reconciliation remain pending.
8. [ ] Initial Server setup and Client Server-trust configuration.
9. [ ] Repository and credential administration.
10. [ ] Storage-layer restore and fidelity: local LV restore and raw LUKS2 container-to-partition restore are implemented; deployment LV acceptance, operator execution of the LUKS2 loop-device and multi-Client multicast runbooks, opened-mapping/LUKS2-on-LV semantics, provisioning/rekeying, and Btrfs snapshot/multi-device support remain pending. No additional LUKS2 implementation work is planned until operator acceptance results identify a concrete defect.
11. [ ] Interrupted-operation recovery.

The [guide index](GUIDES.md) distinguishes available procedures from planned
workflows. Do not publish an operational recipe for an unimplemented path.
Every guide needs prerequisites, supported layouts, exact Cockpit steps, expected results, verification, failure recovery and data-loss warnings. Use version-matched screenshots or clearly labeled mockups, plus role/network diagrams; mockups are illustrative and not runtime acceptance evidence.

## Operator acceptance guides

- [x] Publish step-by-step operator procedures for physical two-machine clone, multi-Client unicast/multicast restore, SSHFS/NFS/SMB/ repository checks, interruption/restart recovery and repository lease protection ([ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md)).
- [ ] Optional operator acceptance: hardware, network and real remote-service runs may be recorded by maintainers, but are not required for software-backlog completion and are not to be simulated or claimed from CI.

## P1 — Governance and release engineering
- [x] Maintainer selected and published GNU GPL v3.0 or later (`GPL-3.0-or-later`) in the repository root LICENSE file.
- [ ] Add reproducible frontend lockfile and deterministic CI installation.
- [ ] Reconcile README, Cockpit README, roadmap, feature matrix and operator docs.
- [ ] Add dependency/security scanning and secret-leak checks.
- [ ] Define Fedora baseline and dependency/version policy.
- [ ] Document configuration backup (excluding PKI private keys), upgrades, rollback and disaster recovery.
- [ ] Document release checksums/signatures and provenance.

## ISO build and acceptance policy
Actually building the ISO is NOT a required completion gate. The documented build procedure is sufficient documentation of how an operator can produce it. Do not spend implementation time generating or publishing an ISO unless the maintainer explicitly requests it. Physical hardware, external network and live-service acceptance are also explicitly outside the requested software scope.

This does not waive software-level checks: Python tests, static checks, frontend dependency installation/build, CI, shell-script validation and documentation/link checks remain project responsibilities. Keep build instructions/scripts maintained. Actual ISO builds, BIOS/UEFI boot, destructive physical-disk tests, target-network PXE boot, switch/IGMP tests and live external repository checks are optional operator activities, not prerequisites for completing the software backlog.

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

## Network configuration status

DHCP/static IPv4 configuration is implemented in Cockpit for the active
NetworkManager profile on the current Server or Client host. The detailed
implementation and remaining runtime-acceptance limitations are recorded in
the following checkpoint. Do not treat profile application as proof of
gateway reachability, DNS resolution or end-to-end Server/Client connectivity.

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
## Capture interruption and staging-residue checkpoint

Normal error paths remove the capture's private staging directory and the
artifact writer's temporary file. A hard process/host crash can bypass those
cleanup paths. The recovery policy is deliberately non-destructive: staging
entries are never automatically removed, promoted, resumed or treated as
committed images. Age, name and PID are insufficient to establish that a
writer is inactive, especially on shared repositories.

The operator acceptance procedure is documented in
[ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md#12-interrupted-capture-staging-residue).
It requires independently stopping/confirming writers, treating residue as
untrusted, starting a fresh capture, and deleting residue only through an
explicit operator decision. Automated stale-residue cleanup and crash-resume
remain out of scope; this is a documented safety boundary, not a claim that
crash recovery is implemented.


## Clonezilla-inspired feature follow-up (2026-11-13)

This section records the requested scope without conflating existing capabilities
with new work. The two research-only items at the end are documentation studies,
not implementation authorization.

### Existing foundations to retain and close

- [x] **Independent image verification (1):** the `verify_image` API and
  Cockpit report already validate stored size/SHA-256, age authentication,
  compression decoding and decoded raw size. Preserve this read-only path;
  add any missing artifact-role coverage only when a concrete gap is found.
- [x] **One image to multiple machines (2):** UDPcast multicast restore already
  distributes a verified image set to multiple authorized Clients. Each Client
  independently selects and validates its own target. This is not a local
  same-host multi-disk restore workflow; do not claim that it is.
- [x] **Filesystem breadth (7), software foundation:** Partclone mappings cover
  ext2/3/4, XFS, NTFS, FAT, exFAT, F2FS and Btrfs, with explicit raw fallback.
  Real disposable-filesystem round trips and exact Fedora utility compatibility
  remain operator validation gates.
- [x] **Post-restore action (8), basic:** the local rescue UI offers no action,
  reboot or poweroff after successful read-back verification. Keep actions
  strictly after successful verification; do not add arbitrary shell execution.
- [~] **Hardware compatibility diagnostics (9), partial:** inventory exposes
  model, vendor, transport, serial, capacity, sector size, partitions and
  storage-layer topology. A consolidated preflight compatibility report
  comparing source requirements with a proposed target is still required.
- [x] **Multicast deployment (11):** authenticated Server/Client coordination
  with UDPcast artifact distribution and per-Client verification/restore is
  implemented. Network-switch IGMP and real multi-host acceptance remain
  operator validation.

### New implementation work

- [x] Add combined read-only source/target proportional-restore preview: reject the same physical block device even when selected through two paths; require independently inspected offline/unused whole disks, matching supported logical-sector sizes and a strictly smaller target; build the preview from source partition metadata and live ext/NTFS minimum-size probes; report existing target partitions and model/serial/WWN; preserve `destructive_confirmation_required=True` and `write_authorized=False`. This remains advisory and does not authorize a destructive operation.

- [ ] **Proportional whole-disk restore layout (3):** implement a separate,
  preview-first partition-layout planner and executor. Preserve partition
  starts and required alignment; define explicit handling for EFI, BIOS boot,
  recovery, swap, LVM, LUKS and unknown filesystems; reject layouts that would
  move or shrink unsupported partitions. Grow only filesystems with a verified
  offline grow tool and a matching post-growth checker. Keep preserve-layout as
  the default and require an exact destructive confirmation. Never edit the
  source image or mutate the target before the complete plan is validated.
- [x] Add read-only whole-disk restore-target inspection: require a real block device resolving as exactly one whole disk; verify offline/unused status with the existing fail-closed source-safety checks; cross-check lsblk and blockdev capacity/logical-sector geometry; inventory existing partition children and stable model/serial/WWN metadata; reject unsupported child storage layers. The result explicitly sets `write_authorized=False`. This is an inspection primitive only: no source/target comparison, target wipe, GPT write, filesystem shrink or restore is authorized.

- [ ] **Read-error-tolerant capture (4):** evaluate GNU ddrescue as an optional
  capture engine for whole disks and supported partitions. Keep a persistent
  mapfile beside private staging state, distinguish complete, recovered-with-
  errors and incomplete results, record bad-sector statistics in a versioned
  manifest extension, and never publish a normal restorable image when
  unreadable ranges remain. Do not silently zero-fill unreadable sectors or
  treat a partial capture as complete. Resume only through an explicitly
  selected, identity-revalidated source and matching mapfile.
- [ ] **Standalone recovery media (5):** define a supported workflow for
  producing a recovery USB/ISO from the existing Feclora Live runtime, with
  architecture/firmware prerequisites, reproducible build inputs, integrity
  checks and a recovery runbook. The existing Live ISO is already bootable;
  this item is about a documented, repeatable recovery-media artifact and
  workflow, not an ISO build performed by the assistant or an implicit
  persistence target.

### Documentation studies only — do not implement yet

- [ ] **Incremental and differential images:** research block-level change
  tracking, dependency-chain integrity, retention, chain compaction, crash
  consistency and full-chain restore/verification semantics. No incremental
  or differential capture, manifest schema, API or UI is authorized yet.
- [ ] **Mountable images and file-level recovery:** research a safe random-
  access image/container format and read-only partition/filesystem exposure,
  including encrypted/compressed artifacts, loop/device-mapper integration,
  namespace isolation, symlink/hardlink handling and selective extraction.
  No image mounting, FUSE export or individual-file restore implementation is
  authorized yet.

Delivery rule: do not mark a new item complete from documentation or a helper
primitive alone. Require runtime/API/Cockpit integration, failure-path tests,
and an acceptance procedure. Never build the ISO as part of this work.

## Filesystem shrink research checkpoint

The current proportional planner supports read-only minimum-size estimates for
ext2/3/4 and NTFS only. XFS and exFAT remain fixed-size in that block-level
planner; XFS can use a separate xfsdump/xfsrestore migration, while exFAT
would require a new filesystem plus file-copy migration. F2FS has an upstream
shrink-specific `resize.f2fs -s` option, but the same manual page also states
that the current version only supports expansion. It therefore remains
disabled pending validation against Feclora's exact Fedora package version.
See [filesystem shrink research](FILESYSTEM-SHRINK-RESEARCH.md). These
migration paths must not be conflated with lossless block-level shrinking.

### Filesystem shrink implementation boundary

- Read-only GPT inspection captures and validates the disk GUID,
  logical sector size and source usable-LBA bounds from `sfdisk --json`.
  The proportional planner now derives the smaller target's final usable LBA
  from the inspected source's trailing GPT-reserved geometry instead of
  assuming 33 reserved sectors. This handles both 512-byte and 4096-byte
  logical sectors and non-default GPT entry-array reservation sizes while
  preserving the source first-usable LBA. A new read-only binary GPT
  validator now checks the protective MBR, primary and backup headers, header
  CRCs, entry-array CRCs, disk GUID, usable bounds, unique partition GUIDs,
  extents, names and array agreement. Source inspection cross-checks those
  bytes against sfdisk's JSON before producing a preview. Tests cover valid
  512-byte and 4096-byte images and corruption/disagreement cases. A pure GPT
  metadata-patch builder now derives a smaller target layout from the validated
  source: it preserves partition slots, GUIDs, names, type GUIDs, attribute
  bits and starts; changes only planned end LBAs; and rebuilds the protective
  MBR, both entry arrays, both headers and their CRCs. It returns aligned byte
  patches and never writes to either stream. Unknown GPT header extensions,
  partition relocation/expansion, missing or duplicate PARTUUIDs and target
  geometry overflow fail closed. Synthetic tests cover rewrite validation and
  relocation rejection. A private-staging applier now consumes the builder:
  it accepts only the verified staging-file descriptor, anchors the open to a
  private owned directory, rejects symlinks/hard links/non-regular files and
  changed source digests, applies bounded patches, truncates the private RAW
  file, fsyncs it, and re-runs the independent binary GPT validator before
  returning its new size and digest. Read-back also compares disk identity,
  usable geometry, partition GUIDs, starts, planned ends, type GUIDs, names
  and attribute bits against the source and plan. It has no block-device write path.
  Synthetic tests cover a smaller-image rewrite and digest-mismatch rejection.
  This remains a low-level staging primitive: it is not wired to the
  proportional restore preview/executor, does not shrink filesystems, and
  does not authorize or perform destination writes.
- GPT inspection and preview records retain per-partition `attrs` from
  `sfdisk --json` (including firmware/OS-specific attribute bits), instead of
  silently dropping them. Source disk identity and header geometry are
  independently validated; the staging-only writer preserves them deliberately
  and validates both rewritten copies before returning.
- A private RAW staging primitive now verifies the stored artifact, checks the
  decoded byte count, writes a mode-0600 copy under a mode-0700 temporary
  directory outside the image repository, and removes that workspace on
  context exit. It does not alter the original artifact and is not yet wired
  into a restore executor.
- ext2/3/4 and NTFS: read-only minimum-size probes are available to the
  preview planner. A staged filesystem-shrink executor, GPT rewrite and
  end-to-end restore integration are still required before smaller-disk
  restore can be enabled.
- XFS: no in-place shrink. A future, separately selected migration may use
  `xfsdump`/`xfsrestore` into a newly created smaller filesystem.
- exFAT: no shrink operation is provided by the standard exfatprogs tool set;
  any future support is a separately verified create-and-copy migration.
- F2FS: keep fixed-size. Upstream `resize.f2fs` documents `-s`, but its
  manual explicitly says the current version only supports expansion. Do not
  infer shrink support from the option flag.
- Regression tests now explicitly reject proportional shortening of XFS,
  F2FS and exFAT partitions. See [filesystem shrink research](FILESYSTEM-SHRINK-RESEARCH.md).

None of the migration workflows above is implemented or authorized for
automatic execution. They require a distinct user-visible mode, private
staging, file-level verification and boot-configuration review.
