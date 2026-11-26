# Engineering roadmap

This page records **remaining engineering work only**. It is not a second
feature inventory or a release-acceptance checklist:

- [Feature and compatibility matrix](FEATURE-MATRIX.md): implemented scope,
  limitations and verification status.
- [Build and validation](BUILD.md): host prerequisites, software checks,
  ISO build and BIOS/UEFI boot procedure.
- [Maintainer acceptance](MAINTAINER-ACCEPTANCE.md): real hardware, destructive
  media, external services and multi-host release evidence.
- [Operator guides](GUIDES.md): user-facing workflows.
- [Engineering references](GUIDES.md#engineering-references): implementation
  contracts, formats and safety boundaries.

## Remaining engineering work

- **Disk recovery:** accept ddrescue acquisition and resume on disposable
  failing media, including a real reboot/resume cycle on the shipped Live
  system.
- **Btrfs:** consider a richer GTK selector for incremental dependency chains.
  Coordinated multi-device block-image capture and profile-aware layer restore
  remain outside the implemented scope.
- **LUKS:** design an opened-mapping workflow only after plaintext byte scope,
  key handling and restore semantics are explicitly approved. Opened-mapping
  restore, LUKS2-on-LV restore, provisioning and rekeying are not implemented.
- **Repository resilience:** expand automated failure-path coverage for
  SSHFS/NFS/SMB and S3, including stale mounts, provider outages, interrupted
  publication, cleanup and service restart.
- **PXE and multi-Client deployment:** extend unattended answer failure-path
  tests and Server-side result reconciliation where required by the product
  contract. Interactive Live PXE, unattended answer-file restore and multicast
  remain separate workflows.
- **Cross-component failure tests:** keep exact-commit CI green for the
  regression suite; perform live service-restart and real two-host
  receiver-loss acceptance separately.
- **Quality and distribution:** complete operational-form and message
  localization; review scanner findings and maintain the backup, upgrade,
  rollback and release-evidence runbook.

## Release acceptance is separate

A successful source test, static check or CI run does not establish BIOS/UEFI
boot, physical-media safety, live-provider interoperability or real-network
deployment. Those checks are listed in
[MAINTAINER-ACCEPTANCE.md](MAINTAINER-ACCEPTANCE.md) and
[BUILD.md](BUILD.md). Do not describe a release as accepted until the owner
records the required evidence.
