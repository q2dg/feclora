# Roadmap

This page summarizes the current implementation and the remaining release work.
The [feature matrix](FEATURE-MATRIX.md) is the capability-level status reference;
the [implementation plan](IMPLEMENTATION-PLAN.md) is the engineering backlog;
and [user requirements and acceptance](USER-REQUIREMENTS-ACCEPTANCE.md) defines
the end-user workflows and their release gates.

## Product model

Feclora is a Fedora Server-based minimal Live appliance. Cage launches Firefox
in kiosk mode and opens the Feclora application in Cockpit; there is no
general-purpose desktop. The Live session is intentionally ephemeral: each
boot creates fresh local credentials, certificates and temporary configuration.
Durable images and manifests belong in repositories explicitly selected by the
operator. Persistent Live-session storage is not a product requirement.

Storage layers and repositories are different concepts. LVM logical volumes,
raw LUKS2 containers and Btrfs filesystems are possible image sources. SSHFS,
NFS and SMB/CIFS are implemented mounted-repository providers. WebDAV and S3
are planned file-repository providers; S3 requires an object API rather than a
mount. NVMe-oF is a separate planned remote block-device transport. Feclora is
a client of these external services and does not provision or administer them.

## Implemented in source

The Cockpit application exposes local whole-disk and partition capture,
restore and cloning; eligible logical-volume capture/restore; image and storage
inventory; operation history; and optional age encryption. The remote stack
includes persistent Server/Client services, managed Server identity and Client
enrollment, Server-authenticated TLS control/unicast transfer, UDPcast
multicast restore, and remote whole-disk and partition cloning. Cockpit also
provides DHCP/static IPv4 profile workflows, PXE preflight and activation,
interactive iPXE boot, and an initial unattended PXE answer workflow.

These statements describe source and Cockpit integration, not release
acceptance. Feclora does not sign image manifests or use detached signature
sidecars. Artifact integrity uses the byte count and SHA-256 digest recorded in
the manifest; authenticity relies on the protected repository and authenticated
transport. Age encryption is optional.

## Remaining engineering work

- **Unattended PXE:** the first NFS-backed whole-disk restore path is integrated.
  Other repository providers, a configurable PXE serving window (maximum
  client count and/or elapsed-time limit), richer Cockpit result
  reconciliation, wrong-passphrase end-to-end acceptance and BIOS/UEFI/
  physical validation remain open. This answer workflow is separate
  from authenticated Server/Client Remote jobs.
- **Remote repositories:** SSHFS, NFS and SMB/CIFS mount lifecycle and image
  engine integration exist. Provider-specific permissions, NFS root-squash,
  stale mounts, outages, interrupted publication, cleanup, concurrency and
  live health behavior still need acceptance. WebDAV's isolated credential
  lifecycle and S3 object API integration are not implemented.
- **Storage fidelity:** deployment-job LV capture, snapshot-assisted LVM/Btrfs
  imaging, multi-device/profile Btrfs capture and layer-aware Btrfs restore
  remain incomplete. Opened-mapping/LUKS2-on-LV restore, provisioning and
  rekeying are unsupported. Raw LUKS2 container-to-partition restore is
  implemented; do not describe all LUKS2 restore as unavailable.
- **Remote cloning and fleet operations:** remote whole-disk and
  partition-to-partition clone paths exist in the shared TLS engine and Cockpit
  job flow. Two-machine fault injection, disconnect/restart recovery and
  complete multi-Client acceptance remain open.
- **Network configuration:** DHCP/static IPv4 application and checkpoint
  rollback exist. Gateway reachability, DNS resolution, inactive-profile
  selection, multi-interface behavior, browser/API disconnect recovery and
  complete Server/Client workflow acceptance remain open.
- **PKI:** managed CA bootstrap, enrollment/renewal, trust inventory/revocation,
  Server leaf renewal/keypair rotation exist. PKI backup and restore are
  excluded from the project scope.
- **Monitoring:** local operation journals and byte progress, plus Server-side
  per-Client operation progress/throughput, exist. Standardized
  phase/diagnostic telemetry, history export, detached-worker supervision and
  additional recovery drills remain open.
- **NVMe-oF:** host-side namespace connection management is not implemented.
  NQN/NSID identity binding, multipath, in-use protection, fabric-security
  boundaries and operator acceptance are required.
- **Release engineering:** the frontend has pinned direct dependencies but no
  committed npm lockfile, so transitive dependency resolution is not
  reproducible. Dependency/security scanning, secret-leak checks,
  documentation/link validation and backup/upgrade/rollback guidance remain
  outstanding.

## Release-critical work

1. Complete unattended PXE lifecycle and result reporting, then validate the
   workflow on supported firmware and hardware.
2. Complete remote repository lifecycle and provider acceptance; implement
   WebDAV and S3 object storage. Treat NVMe-oF as a separate block-device
   workflow.
3. Close storage-layer gaps without weakening fail-closed behavior.
4. Complete remote-clone fault injection, transfer recovery and multi-Client
   acceptance.
5. Complete release engineering: deterministic frontend dependencies,
   security scanning, secret checks and documentation/link checks in CI.
6. Record BIOS/UEFI, real Fedora Live, filesystem, remote-provider, multi-Client,
   PXE, multicast/IGMP and physical-hardware acceptance.

## Operator-owned acceptance

The maintainer builds the ISO. This project documentation describes the
process; ISO generation and publication are not part of the source-validation
work. BIOS/UEFI boot, physical disk writes, remote service behavior, PXE network
boot, multicast switch/IGMP behavior and representative hardware acceptance
must be performed and recorded by an operator. Unit tests and static
validation do not establish those results.

The PKI scope is managed CA bootstrap, enrollment/renewal, trust
inventory/revocation and Server TLS leaf/keypair lifecycle under the existing
CA. PKI backup and restore are out of scope.
