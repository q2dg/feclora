# Roadmap

This page is a high-level status summary. The [feature matrix](FEATURE-MATRIX.md)
is the current capability reference; the [implementation plan](IMPLEMENTATION-PLAN.md)
is the dependency-ordered backlog; and
[USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.md) defines
the release target and acceptance gates.

## Product model

Feclora is a Fedora Server-based minimal Live appliance. It has no
general-purpose desktop: Cage launches Firefox in kiosk mode and opens the
Feclora application in Cockpit. The Live session is intentionally ephemeral.
Each boot creates a fresh session and temporary credentials/configuration;
durable images and manifests belong in repositories explicitly selected by
the operator. No persistent Live-session design is required.

Storage layers and repositories are different concepts. LVM logical volumes,
raw LUKS2 containers/open mappings and Btrfs filesystems are possible image
sources. SSHFS, SFTP, NFS, SMB/CIFS and WebDAV are external repository
mechanisms; BitTorrent is a planned immutable-artifact distribution transport.
Feclora is a client of external infrastructure and does not install or
administer remote servers, exports, shares, trackers or peers.

## Implemented in source and Cockpit

- Fedora Server Live kiosk, first-boot administrator password setup, local
  Cockpit certificate trust and loopback confinement.
- Block-device, partition, LVM, LUKS, Btrfs and Stratis inventory/topology.
- Whole-disk and partition image capture/restore, with manifests, SHA-256,
  compression and optional age/minisign protection.
- Local capture and restore of eligible active LVM logical volumes. Restore
  targets an existing unmounted linear or thin LV; it does not create or resize
  LVM metadata. Raw restores are byte-verified and Partclone restores receive
  a read-only filesystem consistency check. LV images do not include VG/PV
  metadata or dependent storage layers.
- Raw partition capture and restore of verified LUKS2 containers, plus single-device Btrfs partition capture. LUKS2 restore writes the captured raw encrypted bytes (including header/keyslots) to an existing safe partition and verifies the restored LUKS2 UUID/JSON header; it never opens the mapping or handles passphrases. LUKS1/unknown headers and multi-device Btrfs capture fail closed. Opened-mapping images contain plaintext and are deliberately rejected by restore until a separate destination-provisioning/key workflow exists. There is no dedicated opened-mapping capture or snapshot workflow.
- Local disk-to-disk and partition-to-partition cloning.
- Durable local operation queue, systemd worker, progress and journals; an
  interrupted destructive operation is inspected, never automatically
  resumed.
- Authenticated Server/Client enrollment and jobs; unicast image transfer,
  multicast restore and direct whole-disk remote cloning.
- PXE/iPXE boot-tree staging and transient dnsmasq/Caddy/firewalld lifecycle.
  The iPXE menu distinguishes interactive Live boot from an unattended
  handoff path. During an active Server restore job, Feclora publishes and
  revokes a job-bound script containing only non-secret job/Server metadata.

These are source/Cockpit implementation statements, not claims that the ISO,
hardware, provider services or physical networks have passed acceptance.

## Important partial capabilities

- Remote mounted repositories: SSHFS, NFS and SMB/CIFS have client-side
  mount/inventory/image-engine integration, but provider permissions,
  interruptions, NFS root-squash, health and concurrent-reader behavior still
  require provider-by-provider acceptance.
- SFTP: separate signed image-set publish/fetch and Cockpit paths exist, but
  transfers remain limited (single configured directory, synchronous
  metadata/artifact steps, no complete byte-progress/resume workflow).
- PXE job handoff: the active Server restore-job lifecycle publishes/revokes
  the handoff script. Boot parameters are not authorization. The Client does
  not yet automatically authenticate, inspect and bind the job/profile,
  determine a stable target, reach READY or execute unattended.
- Unattended restore profiles: a standalone signed single-use executor exists,
  but profile authoring/activation and integration with PXE Server/Client jobs
  are not complete.
- Network configuration: Cockpit applies DHCP/static IPv4 to an active
  NetworkManager profile with a checkpoint/rollback window; complete
  end-to-end reachability, DNS, multi-interface and Server/Client workflow
  acceptance remains open.
- Local operation telemetry and remote transfer progress have outstanding
  phase/throughput and Server-side byte-progress work.

## Release-critical work

1. **Unattended PXE restore:** integrate authenticated Client startup and
   per-device mTLS identity, bind the Server job/profile/image digest to the
   Client identity, enforce expiry and session replay protection, select a
   deterministic stable target, perform local preflight, report per-Client
   READY/progress/read-back verification, and preserve the explicit
   authorization boundary. PXE boot alone must never authorize a write.
2. **Storage-layer image fidelity:** local LVM logical-volume capture and
   restore are implemented. Server/Client deployment jobs now accept LV
   restore targets over unicast and multicast; both interactive and persistent
   Cockpit Clients select the LV locally, validate it against healthy local
   LVM topology, and run the existing fail-closed LV preflight/restore engine.
   Automated and operator acceptance of multi-Client LV deployments remains
   outstanding. Raw LUKS2 container restore to an existing partition is now
   implemented: it requires explicit encrypted-container provenance and a
   matching header-included UUID, writes raw bytes, verifies read-back and the
   LUKS2 UUID/JSON header, and leaves the container closed. Unicast and
   multicast Client restore runtimes now route `partition` jobs through this
   same verified engine, so remote LUKS2 images inherit the same fail-closed
   provenance and header checks; runtime dispatch tests cover both transports.
   Real remote multi-client/block-device acceptance remains pending. Opened-mapping
   plaintext restore, LUKS2-on-LV, provisioning and rekeying remain unsupported.
   A disposable loop-device acceptance harness now checks wrong-key rejection,
   original-key unlock and plaintext equality; its execution is still pending.
   Finish Btrfs snapshot/multi-device/profile planning and supported restore
   preflights. Do not create or administer VGs/LVs, LUKS devices or Btrfs snapshots
   implicitly.
3. **Remote repositories:** finish credential/provider lifecycle and validate
   each external provider independently; complete SFTP progress/cancellation
   and safe recovery semantics; implement isolated WebDAV credentials.
4. **Remote cloning and deployment:** complete partition-to-partition remote
   cloning, fault injection and transfer telemetry.
5. **Release validation:** build/boot the Live image in BIOS and UEFI, test
   Cockpit/kiosk behavior, real filesystem and storage-layer workflows, remote
   providers, multi-Client jobs and PXE on an isolated lab network. Record
   results; do not infer them from unit tests.

BitTorrent remains a first-class planned distribution transport for immutable,
verified artifacts, at the same priority as the other remote transports. It
is not a writable repository.

## Operator-owned acceptance

The maintainer builds the ISO. Feclora's documentation describes the process;
the project does not generate or publish an ISO as part of this work. BIOS/
UEFI boot, physical disk writes, remote service behavior, PXE network boot,
multicast switch/IGMP behavior and representative hardware acceptance must be
performed and recorded by an operator. Unit tests and static validation do
not establish those results.

Broader CA rotation and trust migration are deferred. The current PKI scope is
managed CA bootstrap, enrollment/renewal, trust inventory/revocation and
Server TLS leaf/keypair lifecycle under the existing CA.
