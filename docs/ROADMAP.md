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

Storage layers and repositories are different concepts. LVM logical volumes, raw LUKS2 containers and Btrfs filesystems are possible image sources. SSHFS, NFS and SMB/CIFS are implemented mounted-repository providers. S3 object storage is the next repository integration. Feclora is a client of external storage services and does not provision or administer them.

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
  Other repository providers, richer Cockpit result reconciliation,
  wrong-passphrase end-to-end acceptance and BIOS/UEFI/physical validation
  remain open. Unattended PXE can count distinct iPXE MAC addresses and enforce optional
  administrator-configured client-count and/or elapsed-time limits; neither
  limit is enabled by default. MAC is an operational identifier, not authentication. This answer workflow is separate
  from authenticated Server/Client Remote jobs.
- **Remote repositories:** SSHFS, NFS and SMB/CIFS mount lifecycle and image-engine integration exist. Provider-specific permissions, NFS root-squash, stale mounts, outages, interrupted publication, cleanup, concurrency and live health behavior still need acceptance. S3 object transfer, credential isolation and manifest-last publication are in progress.

## Operator-owned acceptance

The maintainer builds the ISO. This project documentation describes the
process; ISO generation and publication are not part of the source-validation
work. BIOS/UEFI boot, physical disk writes, remote service behavior, PXE network
boot, multicast switch/IGMP behavior and representative hardware acceptance
must be performed and recorded by an operator. Unit tests and static
validation do not establish those results.

