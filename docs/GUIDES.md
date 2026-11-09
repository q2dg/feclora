---
layout: default
title: Step-by-step guides
---

# Step-by-step guides

These guides describe only workflows that are currently implemented and
exposed in Feclora. A feature marked **planned** is not yet an operator
procedure; do not attempt to reproduce it with undocumented commands.

## Cloning

- [Local disk-to-disk cloning](GUIDE-LOCAL-DISK-CLONE.html) — **Status: available in Cockpit**
  Copy a complete local disk to another local disk, with explicit destination
  confirmation.

- **Remote disk-to-disk cloning** — **Status: planned — not yet available**
  The mTLS transfer engine exists, but its persistent Server/Client service and
  Cockpit workflow are not integrated. No supported end-to-end operator
  procedure is available yet.

## Remote repositories and single-disk imaging

- **Capture an image to an SSHFS repository** — **Status: planned — not yet available**
  SSHFS mount management now exists in Cockpit, but capture/restore cannot yet select a managed repository ID. Provider identity checks, remote publication verification and credential provisioning are still incomplete.

- **Restore an image from an SSHFS repository** — **Status: planned — not yet available**
  The restore engine accepts repository paths, but Cockpit does not yet connect those paths to managed SSHFS repository IDs or provide complete mount recovery.

## Multi-client deployment

- **Restore multiple remote Clients from an SSHFS image repository** — **Status: planned — not yet available**
  Server/Client deployment exists for its configured local repository; remote
  repository integration and the requested SSHFS workflow are not complete.

- **Restore multiple Clients through PXE from an SSHFS image repository** — **Status: planned — not yet available**
  PXE service lifecycle and deployment primitives exist, but this exact
  repository-backed end-to-end workflow is not yet integrated.

- **Unattended multi-client PXE restore from SSHFS** — **Status: planned — not yet available**
  Signed single-use restore-profile primitives exist, but profile authoring,
  fleet authorization and PXE execution are not integrated as this workflow.

## Acceptance testing\n\n- [Physical and remote-environment acceptance](ACCEPTANCE-TESTS.html) — step-by-step operator procedures for two-machine clone, multi-Client unicast/multicast restore, remote repositories, S3 read-only, interruption/restart recovery and repository lease checks. These are operator-run tests, not new implementation features.\n\n## Related technical documentation

- [Feature and compatibility matrix](FEATURE-MATRIX.html)
- [Remote disk-clone protocol and safety model](REMOTE-DISK-CLONE.html)
- [Remote repository architecture and security requirements](REMOTE-REPOSITORIES.html)
- [Server/Client deployment setup](DEPLOYMENT-SETUP.html)
- [Unattended restore profiles and current limits](RESTORE-PROFILES.html)
- [Implementation plan](IMPLEMENTATION-PLAN.html)
