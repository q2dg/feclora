---
layout: default
title: Operator guides
---

# Operator guides

This index reports what the current source exposes through Cockpit. An
implemented code path is not the same as a runtime-accepted workflow. ISO,
hardware, remote-provider and physical-network acceptance remain separate
operator tasks; see [the feature matrix](FEATURE-MATRIX.html).

## Local imaging and recovery

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Storage-layer images

- **LVM logical-volume capture and restore** — **Implemented in local Cockpit**.
  Restore writes into an existing active, uniquely identified, unmounted
  linear or thin LV in a healthy VG. The target must have enough capacity and
  matching logical sector size. Raw images receive exact read-back byte
  verification; Partclone images receive a filesystem-specific read-only
  consistency check. Feclora does not create, resize or repair PVs, VGs or
  LVs. A logical-volume image contains LV bytes, not a backup of its VG/PV
  metadata or other dependent storage layers.
- **LUKS2 container capture** — **Partial**. A partition can be captured as
  raw encrypted bytes after its LUKS2 header and UUID are verified.
  LUKS1/unknown headers fail closed for this layer-aware path. The ordinary
  partition restore writes those bytes to an existing compatible partition;
  Feclora does not unlock or provision encryption.
- **Opened LUKS mapping capture** — **Not available as a dedicated workflow**.
  Inventory and planning can describe mappings, but no mapping-image
  operation is exposed.
- **Btrfs** — **Single-device partition capture and restore only**. The
  manifest records the filesystem UUID and device count; restore refuses
  images without a matching complete single-device dependency. Read-only
  inventory reports Data/Metadata/System allocation profiles on already
  mounted filesystems. Multi-device restore, profile conversion, coordinated
  snapshots and separate subvolume images are not supported. Subvolume
  identifiers are provenance, not image units.
- **Stratis** — inventory only; no Stratis-specific image workflow.

See [the image manifest and storage-layer scope](IMAGE-MANIFEST.html).

## Remote deployment

- [Server trust and Client setup](DEPLOYMENT-SETUP.html) — Cockpit
  workflows for Server certificate trust, deployment jobs and Client-local target approval.
- [Remote whole-disk and partition cloning](REMOTE-DISK-CLONE.html) — **Implemented in
  source/Cockpit**; real two-machine acceptance remains outstanding.
- **Remote partition-to-partition cloning** — **Implemented in source/Cockpit**; two-host acceptance remains outstanding.
- [Deployment control (Server-authenticated TLS)](DEPLOYMENT-CONTROL.html) — protocol,
  job authorization and lifecycle details.
- [Remote repositories](REMOTE-REPOSITORIES.html) — **Partial**. SSHFS, NFS
  and SMB/CIFS mounted-provider integration exists. S3 object-repository integration is in progress.
- [Acceptance procedures](ACCEPTANCE-TESTS.html) — operator-run tests for
  remote services, multiple Clients, interruption and physical networks.

## PXE and unattended deployment

- **Interactive PXE boot** — boot-tree staging and service activation exist;
  BIOS/UEFI network-boot acceptance remains pending. It is intended to boot
  the same Live environment as ISO, then use Cockpit interactively.
- **Unattended PXE answer workflow** — **Partial, end-to-end NFS whole-disk
  path implemented**. The iPXE menu offers an answer-file entry. Cockpit
  publishes one validated JSON answer and an answer-specific script through
  Caddy over HTTP. Live downloads and validates the answer, then invokes the
  existing whole-disk restore engine with stable-target revalidation and
  read-back verification. Before unattended boot, iPXE submits its MAC to a
  loopback admission service behind Caddy. The Server counts distinct MACs,
  permits retries from an already registered MAC, and can stop admitting
  clients at an administrator-configured client cap and/or serving-time
  deadline. Neither limit is enabled by default. The boot script
  is served only through that gate. MAC is spoofable and is not authentication.
  Other repository providers, richer result reporting and physical acceptance
  remain pending.

PXE boot or possession of an answer URL alone never authorizes a destructive
write. The Server-authenticated TLS Remote-jobs workflow remains separate and uses
local Client approval and the Server's explicit ARM step.

## Build, security and acceptance

- [Build and BIOS/UEFI VM procedure](BUILD.html)
- [Cockpit interface and runtime boundaries](COCKPIT.html)
- [Certificate and enrollment policy](CERTIFICATE-MANAGEMENT.html)
- [Six end-user workflows and release acceptance contract](USER-REQUIREMENTS-ACCEPTANCE.html)
- [Implementation backlog](IMPLEMENTATION-PLAN.html)
- [Feature and compatibility matrix](FEATURE-MATRIX.html)

## Illustrations

Guides may use real screenshots or clearly labeled mockups. Mockups are
illustrative only and must not be presented as proof that a feature works.
See the [screenshot and mockup policy](assets/screenshots/README.md).
