# User requirements and end-to-end acceptance contract

This document defines the release target for the bootable Feclora Live system. Cockpit is the primary operator interface. A capability is complete only when its backend/runtime, Cockpit workflow, security and failure behavior, automated tests, operator validation procedure and GitHub Pages guide agree. A library, command builder, prototype, API endpoint or shell-only recipe is not an end-user feature.

## Operating modes

- **Local/rescue:** boot Feclora on the machine whose storage is being operated; discover local devices and perform local clone, capture and restore from Cockpit.
- **Server:** boot Feclora as deployment Server, configure networking, manage repositories and enrolled Clients, and orchestrate jobs from Cockpit.
- **Client:** boot Feclora on each receiver, configure networking, enroll/authorize it, select and locally approve its target, and receive a Server job.
- **PXE Client:** the Server provides the configured PXE/iPXE path so a receiver boots the Feclora Client runtime without manual USB/DVD selection. PXE boot is discovery/transport, never destructive authorization.

DHCP and static IPv4 must be supported independently on Server and Client where networking is required. The UI displays interface, address/prefix, gateway, DNS and link state; validates conflicts/reachability where possible; and distinguishes DHCP client, DHCP/ProxyDHCP server and static endpoint. It must not accidentally start competing DHCP servers on an existing network.

## 1. Local disk/partition cloning

**Outcome:** From Cockpit, clone a local whole disk to another whole disk, or a source partition to a destination partition.

- [ ] Cockpit offers explicit disk-to-disk and partition-to-partition operations.
- [ ] Display stable device identity (model, serial/by-id where available), capacity, logical sector size, partition and mounted/in-use state; never rely on /dev/sdX alone.
- [ ] Validate source and destination independently; never offer the source as its own destination; reject incompatible or undersized targets before writing.
- [ ] Use the installed Partclone engine for supported filesystems; use an explicit byte-for-byte dd fallback for unsupported, unknown or raw content. Report the selected engine and reason.
- [ ] State clearly that the destination is overwritten and require operation- and target-specific confirmation.
- [ ] Show progress, throughput, durable operation history and terminal status in Cockpit.
- [ ] Flush and appropriately verify successful operations. On failure/interruption mark the destination untrusted; never imply rollback.
- [ ] Unit/API/UI tests cover Partclone selection, raw fallback, unsafe source/target, geometry mismatch, short I/O, interruption and verification failure.
- [ ] Publish separate step-by-step guides for whole-disk and partition cloning, with filesystem and partition-table limitations and recovery.

## 2. Remote disk/partition cloning

**Outcome:** Clone a disk or partition between Server and remote Client, with both endpoints configured by DHCP or static network settings.

- [ ] Cockpit supports remote whole-disk and partition-to-partition clone jobs.
- [ ] Server and Client independently support DHCP and static IPv4, with interface selection and visible address/route/DNS state.
- [ ] Server selects/locks a read-only source; Client independently selects and authorizes its destination.
- [ ] Both endpoints authenticate and authorize the exact peer, source and destination. Reachability or PXE boot never authorizes a write.
- [ ] Preflight shows identity, capacity, sector size, mounted/in-use state and connectivity before arming.
- [ ] Streaming is bounded; progress and terminal state appear at both ends; receiver performs read-back verification.
- [ ] Disconnect, timeout, daemon/host restart, partial write and geometry mismatch fail closed. Destructive I/O is never silently resumed; target is marked untrusted.
- [ ] Automated fault injection covers established-session disconnect, timeout and service restart; disposable two-host testing validates the complete operation.
- [ ] Publish separate remote disk-clone and partition-clone guides, including DHCP and static configurations.

Storage-source clarification: LVM logical volumes, raw LUKS2 containers, opened LUKS mappings and Btrfs filesystems are image sources/layers, not repository types. Capture and restore support must describe the exact byte scope and dependencies. Btrfs is imaged at filesystem/block-device level (including supported multi-device sets), not as separate subvolume artifacts. Remote repositories and distribution transports remain the distinct external destinations used to store or deliver those images.

Current-source note: local Cockpit capture supports eligible active LVM logical volumes, verified raw LUKS2 partition containers and single-device Btrfs partition images. Local Cockpit LV restore now supports existing active, unmounted linear/thin targets with raw read-back verification or a read-only Partclone filesystem check; it does not provision or resize LVM metadata. Deployment-job LV restore is implemented in unicast and multicast source paths but still requires exact-commit automated and multi-Client hardware acceptance. Deployment-job LV capture, dedicated opened-mapping capture, coordinated multi-device Btrfs capture, snapshot-assisted capture, opened-mapping restore, LUKS2-on-LV restore, LUKS2 provisioning/rekeying and Btrfs layer-aware restore remain incomplete. Local partition restore supports only raw LUKS2 container images with matching manifest UUID/dependency, exact raw read-back and post-write LUKS2 UUID/JSON header verification; the container remains closed and credentials are not captured or used. An opt-in disposable loop-device acceptance harness additionally runs the unicast Client runtime and Feclora's framed control/artifact transfer protocol over a local socket pair, then tests rejection of a wrong key, unlock with the original key and byte-for-byte plaintext recovery. It does not validate live mTLS negotiation or routed networking. Multicast LUKS2 Client dispatch is covered by automated runtime tests; actual UDPcast/IGMP and two-Client block-device behavior must be recorded using the existing multi-client VM runbook. The loop-device harness has not yet been run on a real Fedora/Linux host, so its execution and recorded host/kernel/cryptsetup/commit remain operator acceptance tasks. The multi-device Btrfs wording above is a release target, not a claim of current support.

## 3. Capture images to remote repositories

**Outcome:** Capture a whole disk, partition or supported storage-layer source (including active LVM logical volumes, raw LUKS2 containers and supported Btrfs filesystems) and publish the image, manifest and integrity metadata to a selected remote repository.

Required client integrations: SSHFS (mounted filesystem), SFTP (file-transfer provider, distinct from SSHFS), NFS, SMB/CIFS and WebDAV. BitTorrent is a first-class peer-to-peer distribution transport for immutable artifacts, at the same priority as the other remote transports; it is not a mounted repository type or a writable repository contract. The distribution model is single-publisher / multi-reader across every transport: one Client publishes each image, while multiple Clients may concurrently read and restore it. Concurrent publishers for the same image are out of scope. Every endpoint/server/export/share/tracker/peer is external infrastructure administered independently of Feclora. Feclora only connects to it as a client; it must not deploy, configure or administer that infrastructure.

- [ ] Cockpit can create, edit, test, connect/mount, inspect, disconnect/unmount and remove each provider advertised as supported.
- [ ] Credentials/private keys use root-owned protected storage; secrets never enter browser storage, ordinary configuration, logs, journals or URLs.
- [ ] SSH host keys are pinned/verified; HTTPS validates TLS certificates
- [ ] Verify provider identity, endpoint/share/path, protocol/filesystem type, access mode, health and free space/quota where available.
- [ ] Cockpit allows selecting the repository and capturing a whole disk, partition or supported active LVM logical volume into it. Raw LUKS2 container capture must verify the header is LUKS2; LUKS1 and unknown headers are unsupported. Btrfs uses filesystem/block-device imaging, not separate subvolume artifacts; unsupported multi-device/profile combinations fail closed.
- [ ] Publication is staged/committed so interrupted uploads cannot appear complete; protect against accidental overwrite and stale mounts. Concurrent readers must see only committed, immutable image sets. Concurrent publishers for the same image are not required.
- [ ] Publish manifest, byte count, SHA-256, optional signature and encryption metadata for subsequent verification.
- [ ] Provider tests cover success, bad credentials, permission denial, insufficient space/quota, disconnect, stale mount, interrupted publication and recovery.
- [ ] WebDAV uses HTTPS with certificate validation and safe per-repository credentials; never use davfs2's global secrets file as a shortcut for isolated repository secrets.
- [ ] BitTorrent distribution verifies a trusted manifest and every artifact digest before any restore; peer availability or torrent metadata is never an authenticity signal. Support cancellation, incomplete-download cleanup, bandwidth/peer policy, explicit seeding controls and concurrent multi-Client restores.
- [ ] Publish a capture guide per provider, distinguishing SSHFS from SFTP and documenting server-side setup.

## 4. Restore a remote image to one local disk

**Outcome:** Browse/select an image in a supported remote repository and restore it to a local whole disk or partition.

- [ ] Cockpit connects to each supported provider and browses inventory without showing an underlying empty mountpoint as if it were the remote repository.
- [ ] Support whole-disk and partition restore with explicit image and destination selection.
- [ ] Verify manifest and artifact hashes, compression integrity and any configured encryption authentication/signature before destructive writes wherever possible. `age` and `minisign` are optional integrations; deployments that do not use them must still establish manifest authenticity through an independently trusted mechanism before unattended/destructive use.
- [ ] Preflight destination geometry, sector size, capacity, partition layout and supported storage layers; summarize before confirmation.
- [ ] Destructive confirmation binds to the exact target and image.
- [ ] Progress, verification, operation journal and failure reason appear in Cockpit.
- [ ] Disconnect, corrupt/truncated image, invalid signature, bad credentials, insufficient capacity and interrupted write fail closed; partially written targets are untrusted.
- [ ] Automated tests cover each provider adapter and restore preflight; integration tests use disposable real provider services.
- [ ] Publish whole-disk and partition restore guides, including provider connection and troubleshooting.

## 5. Mass restore to multiple remote Clients, including PXE

**Outcome:** Select one verified image and restore it to multiple remote Clients in one managed deployment. Each Client can boot Feclora manually or by PXE/iPXE, as configured on the Server.

- [ ] Cockpit supports explicit Client selection and named/stable-identity groups; freeze and display the recipient set before authorization.
- [ ] Select one image from any repository or enabled distribution transport whose read/restore path is supported, including BitTorrent staging only after independent authenticity and digest verification.
- [ ] Each Client independently reports identity, boot mode, network, target, capacity, sector size, safety checks and READY state.
- [ ] Do not start until every required Client is accounted for and independently authorizes its exact destination; missing, duplicate or unexpected Clients block or require explicit resolution.
- [ ] Unicast and multicast modes show eligibility, network requirements and per-Client status. Multicast acceptance includes switch IGMP snooping/querier behavior.
- [ ] PXE/iPXE supports the documented DHCP/ProxyDHCP or isolated-network model, boot delivery, architecture/firmware selection and safe Client handoff.
- [ ] For the existing authenticated multi-Client mTLS workflow, PXE discovery/boot never authorizes destructive restore; enrolled identity and job-bound authorization remain mandatory. This is separate from the identity-free unattended answer workflow.
- [ ] Provide per-Client progress, throughput, terminal verification, failures and exportable deployment report.
- [ ] Define failure isolation: one Client's failure must not misreport other Clients' results.
- [ ] Automated tests cover groups, duplicate/unknown identity, partial readiness, authorization expiry, retry and per-Client reconciliation; VM PXE tests cover BIOS and UEFI. Record physical switch/network acceptance separately.
- [ ] Publish guides for manual Client boot, PXE Client boot, multi-Client unicast and multicast restore.

## 6. Unattended PXE restore from a shared answer file

**Outcome:** An operator prepares one declarative restore answer on the Server. Any compatible PXE-booted Feclora Live client can obtain the same deployment instructions without per-client identity, USB provisioning or enrollment.

- [x] Define a bounded, duplicate-key-rejecting JSON answer schema with operation, image ID, repository URL, stable WWN/serial target selector, explicit destructive confirmation and automatic-start intent.
- [x] Provide one Cockpit answer-file upload; the repository URL is embedded in the JSON.
- [x] Validate uploaded answers and publish the JSON atomically through Caddy over HTTP; support explicit revocation. The operator-selected trust assumption is that the configured HTTP server supplies the intended answer; there is no cryptographic authenticity layer in this PXE flow.
- [x] Publish an answer-specific iPXE entry that boots the same Fedora Live kernel, initramfs and squashfs as the ISO and passes only the job UUID and answer URL.
- [x] Download the answer from Caddy in Live, validate schema/version/size limits, and fail closed on missing or invalid content.
- [x] Connect NFS repository URLs to a read-only mount; reject unsupported schemes rather than accepting syntax as implementation.
- [ ] Connect remaining provider adapters and separately protected credential references.
- [x] Resolve exactly one whole-disk target by WWN and/or serial, verify capacity and device safety through the existing restore engine, and recheck stable identity immediately before the first write.
- [x] Consume the job authorization atomically immediately before the first write to prevent replay during the current Live session.
- [ ] Add cross-reboot expiry/replay protection and tie revocation to cancellation/expiry.
- [x] Execute NFS-backed whole-disk restores through the existing restore engine with post-write read-back verification and a local operation journal.
- [ ] Expose the PXE restore result in the normal Cockpit interface.
- [ ] Ensure the interactive PXE boot opens the same Cockpit experience as ISO Live and does not require the answer file.
- [ ] Adversarial and hardware tests cover modified HTTP answers, replay, ambiguous or changed disks, provider outage, interrupted download and interrupted restore.
- [ ] Validate BIOS and UEFI PXE boot and real hardware restore acceptance before describing the workflow as production-ready.

Per-client TLS identity, USB identity media, manual enrollment and per-client key provisioning are explicitly out of scope for this unattended PXE answer workflow. The existing mTLS Remote jobs workflow remains a separate, identity-based feature.

## Documentation and website acceptance

- [ ] GitHub Pages guide index links every procedure and labels each workflow Available, Partial/limited or Planned consistently with the feature matrix.
- [ ] Each of the six requirements has a user-facing step-by-step guide or a clearly marked Planned entry until complete.
- [ ] Guides include prerequisites, roles, DHCP/static examples where relevant, exact Cockpit navigation, screenshots, expected results, warnings, verification, troubleshooting and recovery.
- [ ] Provider guides state exact supported operations and limitations.
- [ ] Internal links resolve in the rendered Pages site; documentation build/link checks run in CI.
- [ ] README, ROADMAP, FEATURE-MATRIX, GUIDES and IMPLEMENTATION-PLAN agree. No primitive, CLI-only path or acceptance recipe is presented as a completed Cockpit workflow.

## ISO release gate

The maintainer builds the ISO; the project must not generate or publish it. Software completion still requires a reproducible build definition and documented package set. Before calling the requested experience ready, the resulting image must boot in BIOS and UEFI, expose Cockpit, and exercise relevant local/network workflows on disposable devices. Hardware and physical network results are operator acceptance, never inferred from unit tests.

## Global safety and definition of done

- Never overwrite a source or unapproved destination.
- DHCP/PXE discovery, mTLS authentication or possession of a profile alone never authorizes destructive writes.
- Never store secrets in browser state, ordinary config, logs or journals.
- Never report a destination valid after partial or unverified writes.
- Never automatically resume destructive disk writes after interruption.
- A requirement is complete only when Cockpit workflow, backend/runtime, authorization, progress/status, failure handling, automated tests, operator acceptance instructions and published guide all agree.
