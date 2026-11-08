# Roadmap

## Fedora baseline policy

- Current baseline: Fedora Linux 45 x86_64 (GA 3 November 2026).
- The README, Kickstart, runtime package manifest, build/preflight scripts and build runbook must agree on the baseline.
- A baseline bump requires checking RPM availability and package names, rebuilding the Live ISO, and recording BIOS/UEFI boot and storage-workflow results. A version-string-only change is not an accepted migration.

## Milestone 0 — Project foundation
- [x] Create the independent feclora repository.
- [x] Set Fedora Linux 45 x86_64 as the current build baseline and align the README, Kickstart, package manifest, build scripts and build runbook.
- [x] Publish architecture decisions for the single-ISO, multi-mode design and generic-tools-only storage implementation.
- [ ] Define the project license and contribution policy.

## Milestone 1 — Single bootable ISO and startup menu
- [x] Document the reproducible Fedora 45 ISO build procedure and automated preflight (`docs/BUILD.md`); actual build execution and artifact recording remain operator validation.
- [x] Document BIOS/UEFI boot acceptance steps in `docs/BUILD.md` and `tests/VM-SMOKE-TEST.md`; actual VM boot results remain operator validation.
- [ ] Provide predictable live-session startup and logging.
- [x] Implement read-only block-device/filesystem inventory with mocked tests.
- [x] Add a read-only device browser using dialog.
- [x] Add a startup mode selector for Local rescue, Server and Client; Server has an experimental PXE Live-boot path and Client has authenticated unicast plus multi-client multicast restore runtimes (PXE/VM acceptance pending).
- [x] Add an interactive live-console keyboard layout selector, including Spanish; persistence across reboot and UI localization remain pending.
- [x] Select a dedicated Feclora Cockpit application (React + PatternFly) as the web UI architecture; implementation and offline-console parity remain pending.
- [x] Stage and integrate the Python application into the Kickstart build (end-to-end validation pending).
- [x] Add automated build-host preflight checks.
- [ ] Validate inventory, startup menu and UI against real BIOS/UEFI virtual-machine storage.
- [x] Document the build and VM acceptance procedure.

## Milestone 2 — Local imaging and restoration
- [x] Discover generic storage utilities, including filesystem-specific Partclone executables.
- [x] Implement a non-destructive whole-disk selection gate and live-root dependency probe (not yet integrated into the UI).
- [x] Reject mounted, active-swap, busy and device-mapper-held capture/restore devices; protect backing disks of block, overlay and squashfs Live roots (mount-namespace races remain).
- [x] Define versioned disk/partition image manifest schema with safe artifact names, filesystem metadata and SHA-256 integrity.
- [x] Implement bounded-stream artifact writing with atomic no-overwrite publication and SHA-256 metadata (raw, gzip, xz, zstd and lz4), including interactive codec-specific level selection.
- [x] Implement manifest-backed partition capture with Partclone or raw dd, exact raw byte-count validation and manifest-last publication.
- [x] Implement transactional read-only whole-disk capture with raw dd, sfdisk metadata, exact byte-count validation and manifest-last publication.
- [x] Implement verified whole-disk restore with raw dd and none/gzip/xz/zstd/lz4 decompression, target geometry checks and typed confirmation (mocked tests; runtime validation pending).
- [x] Implement partition restore with Partclone and raw fallback (mocked tests; runtime validation pending).
- [x] Implement direct local whole-disk-to-whole-disk clone using bounded raw dd, source/target safety checks, larger-target support and GPT backup-header relocation (mocked tests; runtime validation pending).
- [ ] Complete one-to-one remote disk-to-disk clone between separate source and receiver machines over authenticated, integrity-protected transport (dd sender/receiver, receiver-ready authorization handshake, independent local device selection, one-session TLS wrappers and per-endpoint journaling are implemented; larger targets are accepted and GPT backup metadata is relocated/validated after source-range read-back; CI, interactive UI and physical-device validation remain pending).
- [ ] Implement partition-aware proportional layout restoration, including filesystem-aware growth; raw block cloning must retain original partition starts and must not blindly expand contiguous partitions.
- [x] Add a low-level partition-range parser/copier for whole-disk image extraction (sfdisk dump/JSON validation, bounds/overlap checks, PARTUUID/name selection, bounded pread/pwrite, SHA-256, progress and cancellation); integrated into the disk-image-to-selected-partition extraction and restore workflow.
- [ ] Add direct partition-to-partition cloning with independent source/target selection, mounted/root-device and shared-backing-disk protection, bounded dd streaming, SHA-256 read-back verification, progress and cancellation (runtime and Local rescue UI implemented; mocked tests added but not yet executed; CI and physical-device validation pending).
- [ ] Allow selecting a partition from an existing whole-disk image as a restore source for a selected destination partition; runtime and Local rescue UI are implemented with manifest/signature/digest verification, bounded extraction, and the existing protected restore path. Mocked tests are added but not yet executed; CI and ISO validation remain pending.
- [ ] Allow whole-disk image restore to selected individual partitions without restoring the disk's partition table or unrelated partitions.
- [ ] Add restore layout choices: preserve original partition geometry, proportional expansion, and explicitly selected partition growth; preview the resulting sector layout before destructive confirmation.
- [x] Add strict restore profile schema and stable WWN/serial target matching, including signed, expiring, single-use unattended whole-disk execution and a durable replay ledger (TUI profile authoring and an optional disabled-by-default systemd unit are implemented; operator enablement and physical validation remain pending).
- [x] Implement zstd/lz4 streaming compression and decompression through Fedora system CLI tools (unit and real-binary CI validation are included in GitHub Actions; latest run status must be checked before claiming success).
- [ ] Complete repository-level manifest transactions.
- [ ] Support GPT/MBR, LVM (PV/VG/LV topology, safe activation/deactivation and snapshots), LUKS and boot-area/bootloader workflows.
- [x] Add conservative read-only LVM PV/LV, Stratis mapper and Btrfs filesystem classification to the lsblk inventory; package Stratis management tools.
- [x] Add a read-only LVM PV/VG/LV topology collector using LVM JSON reports (`--readonly`) and include it in storage inventory. Real LVM device validation remains pending.
- [x] Add a read-only Btrfs multi-device topology scan using btrfs-progs, validate reported member counts, include it in storage inventory, and reject partition capture unless the source is proven single-device. Subvolume/snapshot-aware capture/restore and physical-device validation remain pending.
- [x] Add active Stratis pool/filesystem discovery from /dev/stratis and recursively trace device-mapper slaves through sysfs; stopped-pool metadata and physical-device validation remain pending.
- [ ] Add stopped-Stratis-pool metadata, Btrfs subvolume/snapshot topology and filesystem-aware capture/restore workflows; keep unsupported layouts fail-closed.
- [ ] Complete remote repository lifecycle for SSHFS, NFS, SMB/CIFS, WebDAV and S3 (provider validation and mount argv builders exist; credential provisioning, mount lifecycle, durability checks, packaging and integration tests remain).
- [x] Connect disk/partition capture and restore workflows to the Local rescue TUI with explicit destructive confirmation and error dialogs.
- [x] Add optional per-capture age encryption and minisign manifest signing choices; restore requests an age identity and offers trusted-key signature verification (mocked tests; real-binary validation pending).
- [x] Add live dd progress and operator cancellation to direct local disk-to-disk cloning.
- [x] Add live progress and cancellation to whole-disk and partition capture.
- [x] Add live write progress and cancellation to raw whole-disk and raw partition restore.
- [x] Add Partclone stderr progress parsing and operator cancellation to partition restore (packaged-binary validation pending).
- [x] Verify whole-disk restore by reading the destination back and comparing SHA-256.
- [x] Verify raw partition restore by destination read-back SHA-256 and Partclone restore with filesystem-specific read-only consistency checks.
- [x] Add an append-only JSONL operation/error journal for capture, restore and local clone, with per-operation IDs, serialized writes, file/directory fsync and symlink/ownership checks.
- [ ] Validate Partclone progress parsing and operator cancellation with the packaged Partclone build.
- [ ] Validate raw partition read-back SHA-256 and Partclone read-only filesystem consistency checks on disposable devices.
- [x] Add unit tests for operation-journal append, completion, failure, cancellation and symlink rejection.
- [ ] Validate persistent capture/restore/clone event records in the booted Live ISO.
- [ ] Add journal recovery/reconciliation for operations left in started state after a crash.
- [ ] Validate all destructive paths on disposable BIOS/UEFI VMs.

## Milestone 3 — Network client and server modes in the same ISO
- [x] Define and validate the shared versioned deployment job schema.
- [x] Implement the in-memory Server deployment coordinator and client lifecycle state machine.
- [x] Specify one-to-one remote disk clone over TLS 1.3 mTLS, including exact peer identity checks, role/device-bound local authorization, bounded streaming, session SHA-256 and receiver read-back.
- [x] Implement the separate TLS 1.3 mTLS deployment control protocol: certificate identity-to-MAC enrollment mapping, job allowlist enforcement, HELLO/JOB/READY/START/RESULT/CANCEL framing, typed LocalTargetApproval, explicit coordinator arming, managed listener lifecycle and per-client result tracking.
- [x] Implement signed unicast whole-disk image-set transfer over the authenticated TLS session: verify manifest signature and artifact SHA-256/size, stage privately, publish without overwrite, integrate Client capture/sign/send and receive/verify/restore/read-back callbacks. A one-client end-to-end orchestration API is implemented; unit and loopback mTLS tests are added, but CI and real block-device execution remain pending.
- [x] Integrate Server and Client dialog workflows: root-owned runtime configuration, job authoring, certificate identity enrollment mapping, repository selection, local disk inventory, exact typed confirmation, listener/firewall lifecycle, explicit arm and per-client result display. Loopback mTLS tests cover signed-image restore and Client save/upload; execution in GitHub Actions remains pending.
- [x] Add a private append-only SHA-256 hash-chained job journal; coordinator transitions are fsync-persisted before in-memory mutation, and persistence failures fail closed.
- [x] Review prior hash-chained job journals in Server UI, flag incomplete jobs for manual review and refuse corrupt journals; no destructive job is automatically resumed.
- [x] Replay hash-chained job/client events after restart and reconstruct full audit state; provide an explicit, durable operator reconciliation acknowledgement for interrupted jobs. Never recreate sessions or resume destructive I/O automatically.
- [x] Implement Server UI for Client certificate enrollment/rotation and revocation: verify CA chain for TLS client purpose, extract stable SAN identity, bind to one MAC, optionally enroll a minisign public key, and atomically update the root-owned trust config. Private keys and CA issuance remain out-of-band; CRL/OCSP integration remains pending.
- [ ] Implement the Feclora-managed CA workflow in [ADR 0009](adr/0009-managed-deployment-certificates.md): endpoint-local key generation, CSR approval/signing, certificate import, expiry warnings and renewal; retain external PKI support.
- [ ] Implement an auditable trusted-client lifecycle UI with expiry/last-seen information and session termination on revocation; add CRL validation only as defence in depth.
- [x] Select and package the embedded PXE stack: dnsmasq (DHCP/ProxyDHCP/PXE/TFTP), Fedora iPXE BIOS/UEFI boot images, and Caddy for HTTP boot (ADR 0006; services remain disabled by default).
- [x] Document the real PXE VM acceptance procedure for DHCP/ProxyDHCP, TFTP/HTTP, BIOS/UEFI chainloading, signed transfer, disposable-disk restore, read-back and firewalld rollback; actual PXE/deployment execution remains operator validation.
- [x] Add an isolated libvirt PXE VM matrix harness for one Server and BIOS/UEFI Clients; clients remain powered off until Server PXE is ready. VM creation is scripted, but boot and end-to-end acceptance remain manual and unverified.
## Milestone 4 — Mass deployment
- [ ] Implement unicast deployment to multiple clients.
- [x] Select UDPcast as the initial multicast transport (ADR 0008; package included in the Live image).
- [x] Implement a fail-closed UDPcast transport adapter and integrate it with authenticated multi-client whole-disk restore: explicit armed/running-job sender gate, all-client readiness threshold, signed-manifest/source digest verification, private receiver staging, exact size/hash verification, cancellable subprocesses, and scoped firewalld UDP ports (unit tests added; execution and live networking validation pending).
- [x] Integrate UDPcast restore with the mTLS control service, persistent job/client lifecycle, Client-mode local target authorization, private per-client staging, signed-manifest/artifact verification and per-client terminal results. The operator confirms the TTL=1/IGMP/L2 network preflight; automated network capability detection remains pending.
- [ ] Extend the same authenticated multicast restore path to manifest-backed partition images and existing target partitions, with partition-specific local approval, geometry checks and post-write verification.
- [x] Require every selected Client to authenticate and become READY before the explicit manual multicast start; expected-client/deadline policies are present in the coordinator schema but are not yet exposed in the Server UI.
- [x] Persist and display per-client terminal completion/failure results for multicast jobs; live byte-progress and streaming log display remain pending.
- [ ] Add Wake-on-LAN and post-job reboot/poweroff policies.
- [x] Select the Server interface through Server mode and each Client's local multicast receive interface through Client mode; enforce a dedicated TTL=1 239.0.0.0/8 profile and temporary interface-scoped UDP firewall rules. Automated capacity estimation and network capability detection remain pending.
- [x] Document multi-client multicast restore acceptance with one Server and BIOS/UEFI Client VMs in `tests/vm/README.md`; execution, packet-loss/interrupt testing and recorded acceptance results remain operator validation.

## Milestone 5 — Compatibility and expansion
- [ ] Expand filesystem and hardware compatibility based on tested generic tools.
- [ ] Validate age encryption and minisign signing/verification against real binaries on the Fedora Live image.
- [ ] Add encryption and advanced storage coverage where supported.
- [ ] Build a documented compatibility/regression matrix.
- [ ] Evaluate additional deployment workflows only after core Live and Server parity is validated.

Milestones are goals, not claims of existing functionality. Mark items complete only after repeatable tests.


Compression: gzip/xz use the Python standard library; zstd/lz4 are delegated to Fedora's system CLI tools. The menu exposes codec-specific level ranges. Unit and real-binary integration tests are added; execution and ISO validation remain pending.

## Multicast and web interface architecture
- [x] Select a dedicated Cockpit application using React and PatternFly for the future web interface; implementation and console parity remain pending.
- [x] Select and integrate UDPcast for authenticated multi-client whole-disk restore; secure staging and signature/digest verification are implemented. Multicast network compatibility and VM execution remain pending.
