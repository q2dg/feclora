---
layout: default
title: Step-by-step guides
---

# Step-by-step guides

This index distinguishes implemented workflows from partially integrated and
planned workflows. Use the linked technical and operator documentation for
the current Cockpit sequence and safety contract. A feature marked planned is
not an operator procedure. The release-wide acceptance contract is in
[USER-REQUIREMENTS-ACCEPTANCE.md](USER-REQUIREMENTS-ACCEPTANCE.html).

## Local image capture and recovery

- [Whole-disk capture](WHOLE-DISK-CAPTURE.html) — Cockpit operator procedure, compression and optional age/minisign protection.
- [Partition capture](PARTITION-CAPTURE.html) — Cockpit operator procedure and supported Partclone/raw formats.
- [Whole-disk restore](WHOLE-DISK-RESTORE.html) and [partition restore](PARTITION-RESTORE.html) — verification and destructive-write safeguards.
- [Image encryption and signatures](IMAGE-ENCRYPTION.html) — key handling, trust requirements and restore behavior.

The supported operator interface is Cockpit. Screenshot sets will be added
only from real, version-matched Fedora Live sessions; no illustrative or
synthetic screenshot is presented as an actual application screen.

Screenshot procedure and required filenames are listed in [the Cockpit screenshot capture plan](assets/screenshots/README.md). Images will be committed only after capture from a real, version-matched Live build.

## Cloning

- [Local disk-to-disk cloning](GUIDE-LOCAL-DISK-CLONE.html) — **Available in Cockpit**
  Copy a complete local disk to another local disk, with explicit destination
  confirmation.

- [Remote disk-to-disk cloning](REMOTE-DISK-CLONE.html) — **Available in Cockpit**
  Clone a read-only Server source disk to one enrolled Client over the existing
  authenticated persistent Server/Client session. The guide documents both
  endpoint authorization, READY/ARM, streaming and independent read-back.

## Remote repositories and disk imaging

- [Remote repository administration and provider constraints](REMOTE-REPOSITORIES.html) — **Partial; check provider limits**
  SSHFS, NFS and SMB/CIFS have partial Cockpit mount/inventory integration.
  SFTP is a distinct transfer workflow. WebDAV has an incomplete
  provider/credential workflow. BitTorrent is a proposed optional distribution transport, not
  an implemented repository provider. Do not infer capture support for every provider.

- [Whole-disk capture](WHOLE-DISK-CAPTURE.html) and
  [partition capture](PARTITION-CAPTURE.html) — **Available in Cockpit**
  Capture to the local repository or a selected active, verified remote
  repository with write access.

- [Whole-disk restore](WHOLE-DISK-RESTORE.html) and
  [partition restore](PARTITION-RESTORE.html) — **Available**
  Restore from a selected active, verified repository, including read-only
  remote mounts.

- **Remote provider-specific capture/restore recipes** — **Operator acceptance**
  Provider-by-provider test sequences are documented in
  [physical and remote acceptance tests](ACCEPTANCE-TESTS.html). They are
  validation procedures, not additional implementation requirements.

## Multi-client deployment

- [Server/Client deployment setup](DEPLOYMENT-SETUP.html) — **Available**
  Enroll Clients, configure a persistent deployment and use unicast or
  multicast restore. Multi-Client restore can select an active, verified remote
  repository.

- **PXE boot-to-job automatic handoff** — **Planned**
  PXE/iPXE service lifecycle and boot assets exist, but PXE boot does not
  automatically bind a Client to a deployment job or authorize a destructive
  restore. The current workflow remains explicitly operator-controlled.

- **Unattended multi-client PXE restore** — **Planned**
  Signed single-use restore-profile primitives exist, but profile authoring,
  fleet authorization and PXE execution are not integrated end to end.

## Requirements and acceptance

- [Six end-user workflows and release acceptance contract](USER-REQUIREMENTS-ACCEPTANCE.html) — the authoritative checklist for the requested Live/Cockpit experience.

## Acceptance testing

- [Physical and remote-environment acceptance](ACCEPTANCE-TESTS.html) —
  step-by-step operator procedures for two-machine clone, multi-Client
  unicast/multicast restore, SSHFS/NFS/SMB/WebDAV repository checks
  read-only checks, interruption/restart recovery and repository lease
  protection. Physical runs are operator-owned and are not reported as passed
  until actually performed.

## Related technical documentation

- [Tool reuse, repository types and optional transports](TOOLING-AND-TRANSPORTS.html)

- [Feature and compatibility matrix](FEATURE-MATRIX.html)
- [Remote repository architecture and security requirements](REMOTE-REPOSITORIES.html)
- [Unattended restore profiles and current limits](RESTORE-PROFILES.html)
- [Implementation plan](IMPLEMENTATION-PLAN.html)
