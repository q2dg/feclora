# Roadmap

This page distinguishes **engineering work** from **maintainer-run release acceptance**.
The [feature matrix](FEATURE-MATRIX.md) is the capability-level source-status reference;
this roadmap records remaining software engineering work; and the
[maintainer checklist](MAINTAINER-ACCEPTANCE.md) records the hands-on work reserved
for the repository owner.

## Product model

Feclora is a Fedora-based minimal Live appliance built from the `@core` package
group and Feclora's explicit runtime packages. The Textual application starts
directly on tty1; there is no browser or graphical desktop. The Live session is
intentionally ephemeral: each
boot creates fresh local credentials, certificates and temporary configuration.
Durable images and manifests belong in repositories explicitly selected by the
operator. Persistent Live-session storage is not a product requirement.

Storage layers and repositories are different concepts. LVM logical volumes,
raw LUKS2 containers, opened crypt mappings, Btrfs filesystems and existing
Stratis XFS filesystems are distinct source layers with different support
boundaries, documented in the [feature matrix](FEATURE-MATRIX.md). SSHFS, NFS
and SMB/CIFS are mounted-repository providers; S3 is a separate object-storage
provider. Feclora consumes external storage services and does not provision
or administer them.

## Implemented capabilities and workflow boundaries

The implemented capability inventory and its verification status live in the
[feature matrix](FEATURE-MATRIX.md). This roadmap avoids repeating that
inventory; the following product boundaries are important when assessing
remaining work:

- **Interactive PXE** boots the standard Feclora Live runtime and opens the
  normal Textual workflow. PXE is a boot transport, not an image-data proxy.
- **Unattended PXE** is a separate answer-file workflow with narrower admission,
  target-binding and operation semantics. The Live Client resolves the
  repository through its normal repository managers.
- **Multicast deployment** is a separate Server/Client transport and
  coordinator. The unattended PXE adapter is not a multicast implementation.
- **RAW and QCOW2** are formats of the same manifest-backed whole-disk image.
  QCOW2 validation and conversion do not repair guest drivers, initramfs,
  bootloader or firmware configuration, and do not prove guest bootability.
- **Recovery ISO** embeds an image and target-bound answer for guarded boot-time
  restore. It is distinct from the coordinated generic ISO + image + shared
  answer deployment bundle.

These are source/integration boundaries, not a claim of production acceptance.
Image artifacts record byte counts and SHA-256 digests; the digest detects
corruption relative to the manifest, while repository access controls and
authenticated transport provide the trust boundary. Age encryption is optional.

## Remaining engineering work

- **Disk recovery:** GNU ddrescue now retains a private mapfile and partial image, supports bounded direct retry passes, reports mapfile-based progress, and resumes against a stable WWN/serial when available (otherwise the original path plus major:minor identity) and exact geometry. A completed map can be finalized into a normal raw disk image set with SHA-256 and manifest-last publication; degraded maps are rejected. The Textual recovery-jobs page lists local jobs and derives progress from the private mapfile; completed, degraded, interrupted and failed workspaces remain distinct. Automated fault-injection now covers timeout, cancellation, retained mapfiles and resume after cancellation. Remaining work is acceptance with disposable failing media and a real reboot/resume cycle on the shipped Live system.
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
  Live/Textual, unattended answer-file and multicast deployment workflows.
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
  START and checks that every participating Client is marked failed. These
  cases are included in project validation; the exact-commit CI must pass
  before this work is considered complete. A service-level regression also
  verifies that a journal left RUNNING is refused on restart and never resumed;
  live service-restart and real two-host receiver-loss acceptance remain
  maintainer-owned (see [the acceptance checklist](MAINTAINER-ACCEPTANCE.md)).
- **Quality and distribution:** the Live UI is packaged as a Python application
  and uses Fedora's `python3-textual`; UI tests use the pinned test dependency.
  CI verifies the helper allowlist and backend dispatch. CI and GitHub Pages
  also validate local documentation links/assets and illustrated guide cards.
  Remaining work is to resolve scanner findings, finish locale coverage, and
  maintain the backup/upgrade/rollback and release evidence runbook.

## Maintainer-run release acceptance

The repository owner builds the ISO using the documented procedure. The
project work here is to keep that procedure accurate and reproducible; this
assistant does not build or boot the ISO. The owner must then record BIOS and
UEFI boots, Textual behavior on VMs and hardware, restores on disposable
real disks, live remote-provider behavior, multi-Client deployment, and
interactive/unattended PXE on an isolated network. The public operator guides now include task-specific, explicitly labeled
SVG mockups for partition capture/restore, local cloning, repository setup,
PXE, multicast and recovery, in addition to capture, restore and
Server/Client deployment. These mockups explain workflows but are not runtime evidence. Version-matched real screenshots may replace or
supplement them after maintainer acceptance; mockups are not test evidence.

These tasks are listed individually in
[MAINTAINER-ACCEPTANCE.md](MAINTAINER-ACCEPTANCE.md). Unit tests, static
validation and CI do not establish these physical/network results. A release
must not be described as accepted until the owner records them.
