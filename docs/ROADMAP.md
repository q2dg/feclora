# Roadmap

This page is a concise status summary. The [feature matrix](FEATURE-MATRIX.md)
records capability-level implementation detail; the
[implementation plan](IMPLEMENTATION-PLAN.md) is the dependency-ordered
engineering backlog; and
[USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.md) defines the
end-user release target and operator acceptance gates.

## Product model

Feclora is a Fedora Server-based minimal Live appliance. Cage launches Firefox
in kiosk mode and opens the Feclora application in Cockpit; there is no
general-purpose desktop. The Live session is intentionally ephemeral. Each
boot creates fresh local credentials, certificates and temporary configuration.
Durable images and manifests belong in repositories explicitly selected by the
operator. Persistent Live-session storage is not a product requirement.

Storage layers and repositories are different concepts. LVM logical volumes,
raw LUKS2 containers and Btrfs filesystems are possible image sources.
SSHFS, NFS and SMB/CIFS are mounted repository providers; SFTP is a separate
file-transfer provider. WebDAV and S3 are planned file-repository providers;
S3 requires an object API rather than a mount. NVMe-oF is a separate planned
remote block-device transport. Remote servers, exports, shares, buckets and
NVMe subsystems remain external systems administered by their owners.

## Implemented in source and Cockpit

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

These are source and Cockpit implementation statements, not claims that an
ISO, physical hardware, remote provider or physical network has passed
acceptance.

## Partial capabilities and remaining engineering work

- **Remote repositories:** SSHFS, NFS and SMB/CIFS mount lifecycle and image
  engine integration exist. Provider-specific permissions, NFS root-squash,
  stale mounts, outages, interrupted publication, cleanup, concurrency and
  live health behavior still need acceptance. SFTP supports signed-image
  listing/inspection, import, publication and direct restore integration,
  with durable cancellable operations and artifact-boundary progress. It
  remains limited to one configured directory and lacks continuous in-file
  progress, safe resume and multi-directory discovery. WebDAV's isolated
  credential lifecycle is not implemented.
- **Unattended PXE:** the first NFS whole-disk restore path is connected.
  Remaining work includes other repository providers, cross-reboot expiry and
  replay controls, richer Cockpit result reconciliation, wrong-passphrase
  end-to-end acceptance, and BIOS/UEFI/physical validation. The current
  one-use authorization is session-local; it is not cross-reboot replay
  protection. The answer workflow is separate from authenticated Server/Client
  Remote jobs.
- **Storage fidelity:** deployment-job LV capture, snapshot-assisted LVM/Btrfs
  imaging, multi-device/profile Btrfs imaging and layer-aware Btrfs restore
  remain incomplete. Opened-mapping/LUKS2-on-LV restore, provisioning and
  rekeying are unsupported. Raw LUKS2 container-to-partition restore is
  implemented; do not describe all LUKS2 restore as unavailable.
- **Remote cloning and fleet operations:** remote whole-disk and partition-to-partition clone code paths now exist in the shared TLS engine and Cockpit job flow. Two-machine fault injection,
  disconnect/restart recovery and full multi-Client acceptance remain open.
- **Network configuration:** DHCP/static IPv4 application and checkpoint
  rollback exist. Gateway reachability, DNS resolution, inactive-profile
  selection, multi-interface behavior, browser/API disconnect recovery and
  complete Server/Client workflow acceptance remain open.
- **PKI:** managed CA bootstrap, enrollment/renewal, trust inventory/revocation,
  Server leaf renewal/keypair rotation and encrypted CA backup inspection
  exist. Verified CA backup restore/compromise recovery and broader CA
  migration are not implemented.
- **Monitoring:** local operation journals and byte progress, plus
  Server-side per-Client operation progress/throughput, exist. Standardized
  phase/diagnostic telemetry, operation-history export, detached-worker
  supervision and additional recovery drills remain open.
- **S3 object storage:** planned object API integration is not implemented.
  It requires scoped SigV4 credentials, multipart lifecycle and abort/cleanup,
  conditional no-overwrite writes, manifest-last publication, SHA-256 and
  independent manifest authenticity verification.
- **NVMe-oF:** planned host-side namespace connection management is not
  implemented. NQN/NSID identity binding, multipath, in-use protection,
  fabric-security boundaries and operator acceptance are required.
- **Release engineering:** the frontend has pinned direct dependencies but
  no committed npm lockfile; CI currently uses npm install, so transitive
  dependency resolution is not reproducible. Dependency/security scanning,
  secret-leak checks, documentation/link validation and backup/upgrade/
  rollback guidance remain to be completed.

## Release-critical work

1. Complete and validate unattended PXE across supported providers, with
   cross-reboot expiry/replay protection and Cockpit result reconciliation.
2. Complete remote repository provider lifecycle and acceptance, including
   WebDAV and S3 object storage; implement NVMe-oF host access as a separate block-device workflow.
3. Close storage-layer gaps without weakening fail-closed behavior.
4. Complete remote partition-clone fault injection, transfer recovery and
   two-machine acceptance.
5. Complete release engineering: deterministic frontend dependencies,
   security scanning, secret checks and documentation/link checks in CI.
6. Run and record BIOS/UEFI, real Fedora Live, filesystem, remote-provider,
   multi-Client, PXE, multicast/IGMP and physical-hardware acceptance.

## Operator-owned acceptance

The maintainer builds the ISO. Feclora's documentation describes the process;
the project does not generate or publish an ISO as part of this work. BIOS/UEFI
boot, physical disk writes, remote service behavior, PXE network boot,
multicast switch/IGMP behavior and representative hardware acceptance must be
performed and recorded by an operator. Unit tests and static validation do
not establish those results.

Broader CA rotation and trust migration are deferred. The current PKI scope is
managed CA bootstrap, enrollment/renewal, trust inventory/revocation and
Server TLS leaf/keypair lifecycle under the existing CA.
