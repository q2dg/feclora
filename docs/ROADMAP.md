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
- [ ] Build a reproducible Fedora 45 ISO.
- [ ] Boot on BIOS and UEFI in virtual machines.
- [ ] Provide predictable live-session startup and logging.
- [x] Implement read-only block-device/filesystem inventory with mocked tests.
- [x] Add a read-only device browser using dialog.
- [x] Add a startup mode selector for Local rescue, Server and Client; Server/Client currently report unavailable runtimes.
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
- [ ] Support GPT/MBR, LVM (PV/VG/LV topology, safe activation/deactivation and snapshots), LUKS and boot-area/bootloader workflows.\n- [x] Add conservative read-only LVM PV/LV, Stratis mapper and Btrfs filesystem classification to the lsblk inventory; package Stratis management tools. Full VG/pool/subvolume topology and filesystem-aware capture/restore remain pending.
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
- [x] Define and validate the shared versioned deployment job schema (no networking or storage writes).
- [x] Implement the in-memory Server deployment coordinator and client lifecycle state machine (no network transport or storage writes).
- [x] Specify the one-to-one remote clone protocol and implement TLS 1.3 mutual-authentication contexts, exact peer identity checks, role/device-bound local authorization, bounded framing/streaming, session-bound SHA-256, dd-based sender/receiver runtimes and receiver read-back acknowledgements (mocked device-I/O and real TLS 1.3 certificate handshake tests added; CI execution, interactive UI/listener wiring and hardware validation remain).
- [ ] Define the separate authenticated, integrity-protected PXE client/server deployment protocol.
- [ ] Implement client identity, allowlisting and explicit job arming.
- [ ] Implement Client mode runtime using the same generic imaging commands.
- [ ] Implement Server mode control plane, repository management and job lifecycle.
- [x] Select and package the embedded PXE stack: dnsmasq (DHCP/ProxyDHCP/PXE/TFTP), Fedora iPXE BIOS/UEFI boot images, and Caddy for HTTP boot (ADR 0006; services remain disabled by default).
- [ ] Implement the Server-mode runtime for dnsmasq ProxyDHCP and isolated DHCP, interface/subnet safety validation, read-only TFTP, Caddy HTTP boot, and BIOS/UEFI iPXE chainloading (side-effect-free DHCP/Caddy configuration rendering and unit tests are now implemented; actual interface discovery, dnsmasq/Caddy config testing, service lifecycle, firewall integration and boot-file staging remain).
- [ ] Complete one-client unattended save/restore over the network.

## Milestone 4 — Mass deployment
- [ ] Implement unicast deployment to multiple clients.
- [ ] Implement multicast/broadcast transport (evaluate UDPcast and alternatives).
- [ ] Add client-count/deadline/manual deployment start conditions.
- [ ] Add per-client progress, completion, failure reporting and logs.
- [ ] Add Wake-on-LAN and post-job reboot/poweroff policies.
- [ ] Add network interface selection, capacity limits and isolated-network safeguards.
- [ ] Test simultaneous deployment with multiple disposable PXE clients.

## Milestone 5 — Compatibility and expansion
- [ ] Expand filesystem and hardware compatibility based on tested generic tools.
- [ ] Validate age encryption and minisign signing/verification against real binaries on the Fedora Live image.
- [ ] Add encryption and advanced storage coverage where supported.
- [ ] Build a documented compatibility/regression matrix.
- [ ] Evaluate additional deployment workflows only after core Live and Server parity is validated.

Milestones are goals, not claims of existing functionality. Mark items complete only after repeatable tests.


Compression: gzip/xz use the Python standard library; zstd/lz4 are delegated to Fedora's system CLI tools. The menu exposes codec-specific level ranges. Unit and real-binary integration tests are added; execution and ISO validation remain pending.
