# Roadmap

This page distinguishes **engineering work** from **maintainer-run release acceptance**.
The [feature matrix](FEATURE-MATRIX.md) is the capability-level source-status reference;
the [implementation plan](IMPLEMENTATION-PLAN.md) is the detailed engineering backlog;
[requirements and acceptance](USER-REQUIREMENTS-ACCEPTANCE.md) defines the end-user release gates;
and [the maintainer checklist](MAINTAINER-ACCEPTANCE.md) records the hands-on work reserved for the repository owner.

## Product model

Feclora is a Fedora Server-based minimal Live appliance. Cage launches Firefox
in kiosk mode and opens the Feclora application in Cockpit; there is no
general-purpose desktop. The Live session is intentionally ephemeral: each
boot creates fresh local credentials, certificates and temporary configuration.
Durable images and manifests belong in repositories explicitly selected by the
operator. Persistent Live-session storage is not a product requirement.

Storage layers and repositories are different concepts. LVM logical volumes,
raw LUKS2 containers, opened crypt mappings and Btrfs filesystems are potential
image sources/layers. SSHFS, NFS and SMB/CIFS are mounted-repository providers;
S3 is a separate object-storage provider. Feclora consumes external storage
services and does not provision or administer them.

## Implemented in source

The current source and Cockpit application include local whole-disk and
partition capture, restore and cloning; eligible logical-volume capture and
restore; storage inventory and operation history; optional age encryption;
SSHFS/NFS/SMB and S3 repositories; persistent Server/Client jobs over
authenticated TLS; UDPcast multicast restore; remote disk/partition cloning;
P2V conversion/export; interactive PXE; and an unattended PXE whole-disk
answer workflow.

These are source/integration statements, not a claim of production acceptance.
Image artifacts record byte count and SHA-256. Feclora does not sign image
manifests or detached sidecars; authenticity depends on the protected
repository and authenticated transport. Age encryption is optional.

## Remaining engineering work

- **Btrfs:** implement coordinated snapshot-assisted capture, multi-device
  image-set capture/publication, and layer-aware restore for supported
  allocation profiles. Current inventory discovers device membership,
  subvolume/snapshot provenance and chunk/stripe layout; capture preflight
  fails closed for unsupported or incomplete selections. It does not yet
  image multi-device Btrfs sets or create coordinated snapshots.
- **LUKS:** implement a separately designed opened-mapping workflow only if
  its plaintext byte-scope, key handling and restore semantics are approved.
  Current raw LUKS2 container partition imaging/restore preserves the closed
  encrypted container and verifies its header; opened-mapping restore,
  LUKS2-on-LV restore, provisioning and rekeying are not implemented.
- **Repository resilience:** close automated failure-path and recovery
  coverage for SSHFS/NFS/SMB and S3, including stale mounts, provider outages,
  interrupted publication, cleanup and service restart. Do not conflate
  provider integration with acceptance against live services.
- **PXE:** improve unattended answer failure-path coverage and any remaining
  Server-side result reconciliation only if the product contract requires it.
  The current answer workflow keeps operation history on the Live Client and
  the PXE Server serves boot assets and answer JSON only.
- **Release engineering:** finish reproducible frontend dependency locking,
  security/dependency checks, localization coverage and consistent release
  documentation.

## Maintainer-run release acceptance

The repository owner builds the ISO using the documented procedure. The
project work here is to keep that procedure accurate and reproducible; this
assistant does not build or boot the ISO. The owner must then record BIOS and
UEFI boots, Cockpit/kiosk behavior on VMs and hardware, restores on disposable
real disks, live remote-provider behavior, multi-Client deployment, and
interactive/unattended PXE on an isolated network. Real screenshots or
explicitly labeled mockups should be added to the guides.

These tasks are listed individually in
[MAINTAINER-ACCEPTANCE.md](MAINTAINER-ACCEPTANCE.md). Unit tests, static
validation and CI do not establish these physical/network results. A release
must not be described as accepted until the owner records them.
