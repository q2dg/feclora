# Roadmap

This page distinguishes **engineering work** from **maintainer-run release acceptance**.
The [feature matrix](FEATURE-MATRIX.md) is the capability-level source-status reference;
the [implementation plan](IMPLEMENTATION-PLAN.md) is the detailed engineering backlog;
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
P2V conversion/export; interactive PXE; and a shared-answer unattended restore
workflow usable from ISO/USB Live or optional PXE boot. A coordinated ISO+image+
answer bundle workflow now has a build-host coordinator that builds the generic Live ISO, optionally captures an offline disk or selects an existing Feclora image, and atomically packages it with one validated shared unattended DeploymentJob answer. Cockpit also has a durable assembly operation for prebuilt inputs. The answer JSON is still prepared separately; direct job generation in the bundle wizard, removable-media answer discovery, and full end-to-end deployment failure injection remain planned.

Keep the PXE and deployment contracts distinct:

- **Interactive PXE** boots the same Feclora Live runtime used by the ISO and
  opens the normal Cockpit interface. The operator selects the repository,
  image and target Clients in the usual deployment workflow.
- **Unattended PXE** is a separate answer-file workflow with its own admission,
  target-binding and operation limitations. Its repository ID is resolved by
  the Live Client through the normal repository managers; the PXE Server does
  not proxy image data.
- **Multicast deployment** remains its own Server/Client deployment transport
  and coordinator path. The unattended PXE adapter is not a multicast
  implementation and must not be described as one.

P2V now supports explicit `import_p2v`: it verifies the QCOW2 and sidecar, converts to raw sectors, preserves logical sector geometry and publishes a separate Feclora manifest-backed whole-disk image. The imported disk is restorable; GPT/MBR layout is inspected through a read-only loop device and recorded in the manifest. Unpartitioned disks are rejected. Conversion/import does not repair guest boot dependencies or prove VM bootability. A single-disk capture does not coordinate a multi-device Btrfs filesystem; LUKS/LVM sectors are preserved but opened mappings, key provisioning and initramfs integration are not repaired. The separate recovery-ISO builder embeds an image and target-bound answer, but its boot-time embedded-image discovery and restore dispatch remain unfinished. Neither is the coordinated generic ISO + restorable image + shared-answer bundle workflow. See [deployment artifact bundle](DEPLOYMENT-ARTIFACT-BUNDLE.md).

These are source/integration statements, not a claim of production acceptance.
Image artifacts record byte count and SHA-256. The digest detects artifact
corruption relative to the manifest; repository access controls and
authenticated transport form the trust boundary. Age encryption is optional.

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
- **PXE and multi-Client deployment:** preserve the separate interactive
  Live/Cockpit, unattended answer-file and multicast deployment workflows.
  Expand unattended answer failure-path tests and Server-side result
  reconciliation only where the product contract requires it. The Live Client
  keeps its operation history and sends best-effort operational telemetry to
  the PXE Server. The Server serves boot assets and answer JSON; it does not
  mount or proxy image repositories or store image data.
- **Cross-component failure tests:** automated regression cases now cover
  a partial multi-Client disconnect, a remote repository disappearing after
  its usage lease is acquired but before it can be resolved for restore,
  a Client connection resetting before its terminal result is received, and
  durable per-Client outcomes for a partially failed multicast restore.
  A new fault-injection test also covers repository I/O failure after multicast
  START and checks that every participating Client is marked failed. Execute
  the expanded suite on the exact commit; continue with service restart during
  an active operation and real two-host receiver-loss acceptance. These are software
  tests; physical network and multi-host acceptance remains maintainer-owned.
- **Quality and distribution:** frontend direct dependencies and the
  transitive dependency graph are pinned in `webui/package.json` and
  `webui/package-lock.json`; CI and the ISO frontend build use `npm ci`.
  Keep clean-checkout lockfile validation, resolve scanner findings, finish
  locale coverage, and maintain the backup/upgrade/rollback and release
  evidence runbook.

## Maintainer-run release acceptance

The repository owner builds the ISO using the documented procedure. The
project work here is to keep that procedure accurate and reproducible; this
assistant does not build or boot the ISO. The owner must then record BIOS and
UEFI boots, Cockpit/kiosk behavior on VMs and hardware, restores on disposable
real disks, live remote-provider behavior, multi-Client deployment, and
interactive/unattended PXE on an isolated network. The public guides now
include three explicitly labeled SVG mockups for capture, restore and
Server/Client deployment. Version-matched real screenshots may replace or
supplement them after maintainer acceptance; mockups are not test evidence.

These tasks are listed individually in
[MAINTAINER-ACCEPTANCE.md](MAINTAINER-ACCEPTANCE.md). Unit tests, static
validation and CI do not establish these physical/network results. A release
must not be described as accepted until the owner records them.
