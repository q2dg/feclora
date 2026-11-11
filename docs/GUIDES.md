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

- [Whole-disk capture](WHOLE-DISK-CAPTURE.html) — **Implemented in Cockpit**.
- [Partition capture](PARTITION-CAPTURE.html) — **Implemented in Cockpit**;
  includes supported filesystem-aware/raw capture and storage provenance.
- [Whole-disk restore](WHOLE-DISK-RESTORE.html) and
  [partition restore](PARTITION-RESTORE.html) — **Implemented in Cockpit**.
- [Image encryption and signatures](IMAGE-ENCRYPTION.html) — optional age
  encryption and minisign signatures; neither is mandatory for ordinary
  local imaging.
- [Local disk-to-disk cloning](GUIDE-LOCAL-DISK-CLONE.html) — **Implemented
  in Cockpit**.
- [Partition extraction](PARTITION-EXTRACTION.html) — **Implemented in
  Cockpit**; creates a separate partition image from a verified disk image.

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

- [Server/Client setup and enrollment](DEPLOYMENT-SETUP.html) — Cockpit
  workflows for trust enrollment, deployment jobs and Client target approval.
- [Remote whole-disk cloning](REMOTE-DISK-CLONE.html) — **Implemented in
  source/Cockpit**; real two-machine acceptance remains outstanding.
- [Authenticated deployment control](DEPLOYMENT-CONTROL.html) — protocol,
  job authorization and lifecycle details.
- [Remote repositories](REMOTE-REPOSITORIES.html) — **Partial**. SSHFS, NFS
  and SMB/CIFS mounted-provider integration exists; SFTP has a distinct
  signed-image transfer workflow with limitations. WebDAV and BitTorrent are
  not complete provider/transport workflows.
- [Acceptance procedures](ACCEPTANCE-TESTS.html) — operator-run tests for
  remote services, multiple Clients, interruption and physical networks.

## PXE and unattended deployment

- **Interactive PXE boot** — boot-tree staging and service activation exist;
  BIOS/UEFI network-boot acceptance remains pending. It is intended to boot
  the same Live environment as ISO, then use Cockpit interactively.
- **Job-bound PXE handoff** — **Partial**. The iPXE menu offers an unattended
  handoff choice. During an active Server restore job, Feclora can publish
  and later revoke a public script containing only the job UUID, Server
  address and mTLS control port. These values are metadata, not authorization.
  The Client does not yet automatically authenticate, inspect the job,
  select/verify its target, or enter the READY/ARM workflow from this boot.
- **Unattended PXE restore** — **Partially implemented**. Each enrolled
  Client exports its mTLS identity to dedicated removable media; the Live
  image mounts it read-only and automatically starts the Client for unattended
  boots. One Client per unicast whole-disk job requires an exact WWN/serial
  binding and retains the Server READY/ARM gate. Partition/multicast execution,
  interrupted-job replay acceptance and BIOS/UEFI lab validation remain.

PXE boot alone never authorizes a destructive write. Manual Client approval
and the Server's explicit ARM remain required by the current deployment
workflow.

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
