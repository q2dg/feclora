# Roadmap

## Milestone 0 — Project foundation
- [x] Create the independent feclora repository.
- [x] Define Fedora 43 x86_64 as the initial target.
- [x] Publish architecture decisions for the single-ISO, multi-mode design and generic-tools-only storage implementation.
- [ ] Define the project license and contribution policy.

## Milestone 1 — Single bootable ISO and startup menu
- [ ] Build a reproducible Fedora 43 ISO.
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
- [x] Implement bounded-stream artifact writing with atomic no-overwrite publication and SHA-256 metadata (raw, gzip and xz).
- [x] Implement manifest-backed partition capture with Partclone or raw dd, exact raw byte-count validation and manifest-last publication.
- [x] Implement transactional read-only whole-disk capture with raw dd, sfdisk metadata, exact byte-count validation and manifest-last publication.
- [x] Implement verified whole-disk restore with raw dd and none/gzip/xz decompression, target geometry checks and typed confirmation (mocked tests; runtime validation pending).
- [x] Implement partition restore with Partclone and raw fallback (mocked tests; runtime validation pending).
- [ ] Implement disk-to-disk clone using partition-table tools and per-partition imaging.
- [ ] Implement zstd/lz4 streaming adapters and repository-level manifest transactions.
- [ ] Support GPT/MBR, LVM, LUKS and boot-area/bootloader workflows.
- [ ] Support local and remote repositories (SSH/SFTP, NFS, SMB/CIFS, WebDAV).
- [x] Connect disk/partition capture and restore workflows to the Local rescue TUI with explicit destructive confirmation and error dialogs.
- [ ] Add live progress, logs, cancellation, post-write verification and crash recovery to the TUI workflows.
- [ ] Validate all destructive paths on disposable BIOS/UEFI VMs.

## Milestone 3 — Network client and server modes in the same ISO
- [x] Define and validate the shared versioned deployment job schema (no networking or storage writes).
- [x] Implement the in-memory Server deployment coordinator and client lifecycle state machine (no network transport or storage writes).
- [ ] Define the image manifest and authenticated, integrity-protected client/server protocol.
- [ ] Implement client identity, allowlisting and explicit job arming.
- [ ] Implement Client mode runtime using the same generic imaging commands.
- [ ] Implement Server mode control plane, repository management and job lifecycle.
- [ ] Integrate DHCP safely (existing DHCP detection, explicit relay/proxy or dedicated isolated subnet; no silent DHCP server).
- [ ] Implement TFTP and PXE/iPXE boot for legacy BIOS and UEFI clients.
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
- [ ] Add encryption and advanced storage coverage where supported.
- [ ] Build a documented compatibility/regression matrix.
- [ ] Evaluate additional deployment workflows only after core Live and Server parity is validated.

Milestones are goals, not claims of existing functionality. Mark items complete only after repeatable tests.
