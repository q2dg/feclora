# User requirements and end-to-end acceptance contract

This document defines the release target for the bootable Feclora Live system. Cockpit is the primary operator interface. A capability is complete only when its backend/runtime, Cockpit workflow, security and failure behavior, automated tests, operator validation procedure and GitHub Pages guide agree. A library, command builder, prototype, API endpoint or shell-only recipe is not an end-user feature.

## Operating modes

- **Local/rescue:** boot Feclora on the machine whose storage is being operated; discover local devices and perform local clone, capture and restore from Cockpit.
- **Server:** boot Feclora as deployment Server, configure networking, manage repositories and selected Client MACs, and orchestrate jobs from Cockpit.
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

- [x] Cockpit exposes remote whole-disk and partition-to-partition clone jobs with source-type selection and Client-local destination selection. Two-host destructive acceptance remains a separate gate.
- [ ] Server and Client independently support DHCP and static IPv4, with interface selection and visible address/route/DNS state.
- [ ] Server selects/locks a read-only source; Client independently selects and authorizes its destination.
- [ ] Both endpoints authenticate and authorize the exact peer, source and destination. Reachability or PXE boot never authorizes a write.
- [ ] Preflight shows identity, capacity, sector size, mounted/in-use state and connectivity before arming.
- [ ] Streaming is bounded; progress and terminal state appear at both ends; receiver performs read-back verification.
- [ ] Disconnect, timeout, daemon/host restart, partial write and geometry mismatch fail closed. Destructive I/O is never silently resumed; target is marked untrusted.
- [ ] Automated fault injection covers established-session disconnect, timeout and service restart; disposable two-host testing validates the complete operation.
- [ ] Publish separate remote disk-clone and partition-clone guides, including DHCP and static configurations.

Storage-source clarification: LVM logical volumes, raw LUKS2 containers, opened LUKS mappings and Btrfs filesystems are image sources/layers, not repository types. Capture and restore support must describe the exact byte scope and dependencies. Btrfs is imaged at filesystem/block-device level (including supported multi-device sets), not as separate subvolume artifacts. Remote repositories and distribution transports remain the distinct external destinations used to store or deliver those images.

Current-source note: local Cockpit capture supports eligible active LVM logical volumes, verified raw LUKS2 partition containers and single-device Btrfs partition images. Local Cockpit LV restore now supports existing active, unmounted linear/thin targets with raw read-back verification or a read-only Partclone filesystem check; it does not provision or resize LVM metadata. Deployment-job LV restore is implemented in unicast and multicast source paths but still requires exact-commit automated and multi-Client hardware acceptance. Deployment-job LV capture, dedicated opened-mapping capture, coordinated multi-device Btrfs capture, snapshot-assisted capture, opened-mapping restore, LUKS2-on-LV restore, LUKS2 provisioning/rekeying and Btrfs layer-aware restore remain incomplete. Local partition restore supports only raw LUKS2 container images with matching manifest UUID/dependency, exact raw read-back and post-write LUKS2 UUID/JSON header verification; the container remains closed and credentials are not captured or used. An opt-in disposable loop-device acceptance harness additionally runs the unicast Client runtime and Feclora's framed control/artifact transfer protocol over a local socket pair, then tests rejection of a wrong key, unlock with the original key and byte-for-byte plaintext recovery. It does not validate live Server-authenticated TLS negotiation or routed networking. Multicast LUKS2 Client dispatch is covered by automated runtime tests; actual UDPcast/IGMP and two-Client block-device behavior must be recorded using the existing multi-client VM runbook. The loop-device harness has not yet been run on a real Fedora/Linux host, so its execution and recorded host/kernel/cryptsetup/commit remain operator acceptance tasks. The multi-device Btrfs wording above is a release target, not a claim of current support.

## 3. Capture images to remote repositories

**Outcome:** Capture a whole disk, partition or supported storage-layer source (including active LVM logical volumes, raw LUKS2 containers and supported Btrfs filesystems) and publish the image, manifest and integrity metadata to a selected remote repository.

Required repository integrations: SSHFS, NFS and SMB/CIFS mounted filesystems, plus S3-compatible object storage through its HTTPS API. S3 requires scoped credentials, TLS validation, multipart lifecycle, conditional no-overwrite publication and a manifest-last commit marker. The distribution model is single-publisher / multi-reader for committed image sets. Concurrent publishers for the same image are out of scope. Every endpoint, bucket, export, share, subsystem and namespace is external infrastructure administered independently of Feclora. Feclora must not deploy or administer that infrastructure.

- [ ] Cockpit can create, edit, test, connect/mount, inspect, disconnect/unmount and remove each provider advertised as supported.
- [ ] Credentials/private keys use root-owned protected storage; secrets never enter browser storage, ordinary configuration, logs, journals or URLs.
- [ ] SSH host keys are pinned/verified; HTTPS validates TLS certificates
- [ ] Verify provider identity, endpoint/share/path, protocol/filesystem type, access mode, health and free space/quota where available.
- [ ] Cockpit allows selecting the repository and capturing a whole disk, partition or supported active LVM logical volume into it. Raw LUKS2 container capture must verify the header is LUKS2; LUKS1 and unknown headers are unsupported. Btrfs uses filesystem/block-device imaging, not separate subvolume artifacts; unsupported multi-device/profile combinations fail closed.
- [ ] Publication is staged/committed so interrupted uploads cannot appear complete; protect against accidental overwrite and stale mounts. Concurrent readers must see only committed, immutable image sets. Concurrent publishers for the same image are not required.
- [ ] Publish manifest, byte count, SHA-256, optional signature and encryption metadata for subsequent verification.
- [ ] Provider tests cover success, bad credentials, permission denial, insufficient space/quota, disconnect, stale mount, interrupted publication and recovery.
- [ ] S3 object storage supports authenticated inventory, bounded multipart transfer, abort/cleanup of incomplete uploads, immutable object keys, conditional manifest-last publication, independent manifest authenticity and SHA-256/size verification, cancellation and concurrent readers.
- [ ] Publish a capture guide per provider, documenting server-side setup.

## 4. Restore a remote image to one local disk

**Outcome:** Browse/select an image in a supported remote repository and restore it to a local whole disk or partition.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## 5. Mass restore to multiple remote Clients, including PXE

**Outcome:** Select one verified image and restore it to multiple remote Clients in one managed deployment. Each Client can boot Feclora manually or by PXE/iPXE, as configured on the Server.

- [ ] Cockpit supports explicit Client selection and named/stable-identity groups; freeze and display the recipient set before authorization.
- [ ] Select one image from any repository or enabled distribution transport whose read/restore path is supported, including S3 object retrieval only after independent manifest authenticity and artifact digest verification.
- [ ] Each Client independently reports identity, boot mode, network, target, capacity, sector size, safety checks and READY state.
- [ ] Do not start until every required Client is accounted for and independently authorizes its exact destination; missing, duplicate or unexpected Clients block or require explicit resolution.
- [ ] Unicast and multicast modes show eligibility, network requirements and per-Client status. Multicast acceptance includes switch IGMP snooping/querier behavior.
- [ ] PXE/iPXE supports the documented DHCP/ProxyDHCP or isolated-network model, boot delivery, architecture/firmware selection and safe Client handoff.
- [ ] For the existing multi-Client Remote jobs workflow, PXE discovery/boot never authorizes destructive restore; local target confirmation and explicit Server ARM remain mandatory. Clients are not individually authenticated. This is separate from the identity-free unattended answer workflow.
- [ ] Provide per-Client progress, throughput, terminal verification, failures and exportable deployment report.
- [ ] Define failure isolation: one Client's failure must not misreport other Clients' results.
- [ ] Automated tests cover groups, duplicate/unknown identity, partial readiness, retry and per-Client reconciliation; VM PXE tests cover BIOS and UEFI. Record physical switch/network acceptance separately.
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
- [x] Consume the job authorization atomically immediately before the first write to prevent a second write from the same authorization during the current Live session.
- [x] Add optional Server-side PXE serving limits: Cockpit asks the administrator for a distinct-client cap and/or elapsed-time deadline; both are unset by default, so no MAC-count or time limit is imposed unless explicitly configured. The iPXE MAC is registered on first admission when a client cap is enabled, and retries from an already registered MAC do not consume another slot. The protected boot script cannot be fetched directly around the admission endpoint. MAC is an operational identifier, not authentication; a client can spoof it.
- [x] Execute NFS-backed whole-disk restores through the existing restore engine with post-write read-back verification and a local operation journal.
- [ ] Expose the PXE restore result in the normal Cockpit interface.
- [ ] Ensure the interactive PXE boot opens the same Cockpit experience as ISO Live and does not require the answer file.
- [ ] Adversarial and hardware tests cover modified HTTP answers, repeated answer requests, ambiguous or changed disks, provider outage, interrupted download and interrupted restore.
- [ ] Validate BIOS and UEFI PXE boot and real hardware restore acceptance before describing the workflow as production-ready.

Per-client TLS identity, USB identity media, manual enrollment and per-client key provisioning are explicitly out of scope. The Remote jobs workflow also does not use Client identity or client authentication.

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
- DHCP/PXE discovery, TLS Server authentication, MAC selection or possession of a profile alone never authorizes destructive writes.
- Never store secrets in browser state, ordinary config, logs or journals.
- Never report a destination valid after partial or unverified writes.
- Never automatically resume destructive disk writes after interruption.
- A requirement is complete only when Cockpit workflow, backend/runtime, authorization, progress/status, failure handling, automated tests, operator acceptance instructions and published guide all agree.
