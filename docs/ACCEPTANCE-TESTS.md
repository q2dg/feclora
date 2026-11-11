# Physical and remote-environment acceptance guide

This document is an operator runbook for acceptance testing on disposable
hardware and independently operated remote-storage services. It does not
describe new software features and does not make physical testing a
prerequisite for continuing software development. All SSH/SFTP, NFS, SMB,
WebDAV and BitTorrent infrastructure is external to Feclora: the operator
or service owner provisions and administers it. Feclora tests only its client
connection, authentication, authorization, transfer/mount behavior, integrity
checks and failure handling. No test step asks Feclora to install or configure
a remote server/export/share/tracker. Record the Feclora commit, host
models, firmware mode, network topology, repository provider/version, test
date and outcome for every run.

## Safety rules for every test

1. Use only disks and machines explicitly reserved for destructive testing.
   Disconnect or positively identify every production/system disk.
2. Keep a separate, verified backup of anything that must survive.
3. Record each disk's model, serial, capacity, logical sector size and
   /dev/disk/by-id path before starting. Do not rely on /dev/sdX ordering.
4. Confirm the source/target roles with two people for destructive multi-host
   tests. Use Feclora's exact local target confirmation and Server ARM phrase.
5. Never interpret a disconnect or failed test as rollback. Once a target
   writer has started, the destination may be partially or fully overwritten.
   Mark it untrusted until a later complete operation and verification.
6. Do not interrupt power to a production host or disconnect a production
   storage service. Fault injection belongs on disposable test equipment.
7. Preserve Server and Client operation logs and deployment journals with the
   test record. Redact credentials, private keys and secret configuration.

## 1. Two-machine disk clone

**Purpose:** verify one-to-one Server-to-Client cloning with real block devices.

Prerequisites: two disposable machines, one read-only source disk, one target
disk at least as large as the source, enrolled Server/Client identities, and
a wired network path between the hosts.

1. Boot both machines and verify their hostnames, network interfaces and
   enrolled identities.
2. On the source host, identify the intended source by model, serial and
   /dev/disk/by-id. Verify it is a whole disk and reports read-only (RO=1).
3. On the receiver, identify the disposable target independently. Verify its
   capacity and logical sector size are compatible with the source.
4. In Cockpit, create a unicast clone deployment, select the source disk and
   authorize exactly the enrolled receiver.
5. On the receiver, inspect the authenticated job, select the local target and
   enter the exact destructive confirmation displayed by Feclora.
6. On the Server, verify the READY receiver identity and enter the exact
   job-specific ARM phrase. Do not substitute a generic confirmation.
7. Wait for transfer, receiver read-back and terminal verification to finish.
8. Confirm both endpoints report the same completed job/session, byte count
   and SHA-256 result. Confirm the receiver's operation journal records
   completion.
9. Power down the receiver and inspect the cloned partition table and
   filesystems from a separate maintenance environment. Do not mount a
   filesystem read-write if the source disk will also be attached.
10. Save logs and record the result. If any step fails after writing starts,
    mark the target untrusted; do not assume it is unchanged.

Repeat with a larger target to verify supported GPT backup-header relocation.
Repeat with an undersized target and a mismatched logical sector size to
confirm that Feclora rejects the target before writing.

## 2. Multi-client restore: unicast and multicast

**Purpose:** verify the persistent Server/Client restore workflow with more
than one physical receiver.

Prerequisites: a verified image with its manifest authenticated through the configured trust mechanism in the selected repository, at least
two disposable Client machines, enrolled identities, and a dedicated test
network. Multicast additionally requires a network whose IGMP snooping and
querier behavior has been independently configured and checked.

1. Verify the image manifest and every referenced artifact in Cockpit before
   creating the deployment. A present signature must verify against an
   independently trusted key; an encrypted artifact must decrypt/authenticate
   with the configured age identity. Do not treat SHA-256 alone as publisher
   authentication.
2. Record each Client's target disk identity, capacity, sector size and
   existing partition layout. Confirm all targets are disposable.
3. For unicast, create a restore job for one enrolled Client and complete the
   READY, ARM, restore and read-back verification sequence. Repeat separately
   for the next Client.
4. For multicast, create one restore job authorizing at least two Clients.
   Confirm each Client has selected and locally authorized its own target.
5. Check the Server reports every intended Client READY before ARM. A missing
   or unexpected Client must prevent the operation from starting.
6. Enter the multicast-specific confirmation only after the test network's
   IGMP behavior has been verified. Do not infer multicast readiness merely
   from successful unicast traffic.
7. Monitor per-Client progress and terminal state. Confirm every Client
   reports successful verification; one successful receiver does not prove
   the others completed.
8. Reboot each receiver and inspect the resulting disk layout and bootability
   appropriate to the test image.
9. Save the Server journal and each Client's operation log.

## 3. Remote repository provider acceptance

The hardware-independent repository-manager test suite also covers concurrent
registry mutation: simultaneous additions for different IDs must preserve both
entries, a symlink substituted for the registry lock must be rejected, and a
simulated registry-write failure during removal must leave the definition and
its empty mountpoint intact. These tests protect Feclora's local
registry only; they are not tests of remote image publication. Remote image
distribution follows a single-publisher / multi-reader contract: one Client
publishes an image and multiple Clients may read/restore it concurrently.

Run this procedure independently for each configured SSHFS, NFS and SMB/CIFS
endpoint. WebDAV is currently rejected by the repository manager until its
per-repository encrypted credential lifecycle is implemented; do not attempt
to enable it by writing `/etc/davfs2/secrets`. Use a dedicated test
account/export/share and a disposable image. Do not reuse production credentials.

1. Prepare the provider endpoint and provision credentials using the
   provider's root-protected mechanism. Verify SSH host keys for SSHFS, NFS
   export ownership/mapping or SMB share permissions as appropriate. WebDAV
   HTTPS and isolated-credential acceptance must wait for its implementation.
2. Add the repository in Cockpit with the correct provider, endpoint/share,
   remote path and access mode. Credential contents must never be pasted into
   Cockpit fields or stored in ordinary project configuration.
3. Mount it through Feclora. Confirm Cockpit reports mounted and **identity verified** and that provider source, filesystem type and access mode match the intended endpoint. This check reads mount metadata via `findmnt` with a five-second subprocess timeout; timeout or malformed output is an error, not a successful check. It is not a live connectivity, read/write, latency, free-space or quota health probe. A stale mount may still pass identity verification.
4. Exercise the remote path with a real inventory/read operation after identity verification. Confirm that it completes (not merely that the mount is listed as verified), then open the repository image inventory. Confirm it lists only images from the
   selected verified repository, not files from the local directory beneath
   an unmounted mountpoint.
5. For a read/write provider, have one Client capture and publish a small
   disposable test disk to that repository. Verify its manifest, signature,
   artifact byte counts and cryptographic digests, then restore it to a
   disposable target and verify read-back.
6. Using the committed image from step 5, have at least two other Clients read
   the same repository image and restore it concurrently to separate disposable
   targets. Verify each Client independently reports successful integrity and
   read-back checks, and confirm the remote image set remains unchanged. This
   exercises the single-publisher / multi-reader contract; do not test
   concurrent publishers.
7. For a read-only mount, confirm inventory, inspection and verification work,
   and confirm capture/extraction controls are unavailable.
8. For NFS, explicitly test the configured root-squash/ownership policy.
   Root-owned manifest validation must remain enforced; a manifest mapped to
   an anonymous UID is expected to be rejected.
9. Unmount through Feclora, confirm the mount is gone, and verify the
   repository definition remains available for a later mount.
10. Record provider version, mount options, identity/access-mode verification,
    actual I/O outcomes, throughput observations, and all failures. Do not record a passing identity check as a passing health check. Never include secrets in the report.

## 5. Interrupted operation, disconnect and restart recovery

This is destructive fault injection. Use a disposable source/target pair and
an image whose loss is acceptable.

1. Complete a normal baseline clone or restore and preserve its logs.
2. Start a second operation using a different disposable target.
3. After the receiver has demonstrably begun writing, interrupt the test
   network or stop the disposable peer. Do not interrupt a production system.
4. Confirm the receiver reports failure/interruption rather than success and
   that the partial target is not presented as verified.
5. Restore network connectivity. Confirm Feclora does not silently resume the
   old destructive operation.
6. Restart the disposable Server service or host while the job is active in a
   separate run. Inspect the durable journal after restart.
7. Confirm recovery reconstructs the last durable job/client state, marks an
   active job interrupted, and requires explicit operator reconciliation.
   Reconciliation must not recreate sessions or restart disk I/O.
8. Reinitialize or replace the disposable target, then create a new job with
   fresh authorization and verify it end to end.
9. Preserve both endpoints' journals and record exactly when the failure was
   injected and how much data may have been written.

There is no rollback guarantee after the writer starts. The expected safe
outcome is a failed/interrupted job, a destination treated as untrusted, and
no automatic replay.

## 6. Repository lease and unmount protection

This test verifies that an active persistent restore owns its remote repository
for the full service lifetime.

1. Configure and verify a disposable read-only or read/write remote repository
   containing a signed image suitable for restoration.
2. Create and start a remote-repository restore job with a disposable Client.
3. Once the persistent Server service has acquired the repository usage lease,
   attempt to unmount the repository through Cockpit or the supported manager
   action.
4. Confirm unmount is refused while the lease is held and the active restore
   continues to resolve the same verified repository.
5. If safe for the test, simulate the mount disappearing outside Feclora.
   Attempt to remove the repository definition. Confirm removal is refused
   while the service still owns the lease.
6. Allow the restore to reach a terminal state, then stop the persistent
   deployment service.
7. Retry unmount and, if desired, definition removal. Confirm they now succeed.
8. Record the job ID, repository ID, lease lifetime and each attempted action.

The expected protection is fail-closed: an active restore must not lose its
repository definition or be unmounted through Feclora while its service holds
the shared lease.

## Results record

For each run, record:

- Feclora commit SHA and workflow status.
- Test date, operator and test case number.
- Host model, firmware mode, disk model/serial/capacity/sector size.
- Network topology, link speed and multicast/IGMP configuration where used.
- Repository provider, server version, filesystem/API version and mount mode.
- Job/session ID, image ID, byte counts, verification result and elapsed time.
- Failure injection point, observed terminal state and recovery action.
- Links or protected locations for redacted logs and journal exports.
- Outcome: **pass**, **fail**, or **not run**. Never mark a test passed from
  unit-test results alone.


## 9. Filesystem-aware partition capture and restore

Run each case on a disposable VM disk/partition formatted with the named
filesystem. Use the exact Partclone and filesystem-checker packages included
in the target Feclora Live image. Record package versions and tool paths.

| Filesystem | Expected capture/restore utility | Post-restore check |
|---|---|---|
| ext2 / ext3 | partclone.extfs | e2fsck -f -n |
| ext4 | partclone.ext4 | e2fsck -f -n |
| XFS | partclone.xfs | xfs_repair -n |
| NTFS (including ntfs3 kernel FSTYPE) | partclone.ntfs | ntfsfix --no-action |
| FAT12 / FAT16 / FAT32 / vfat | partclone.fat | fsck.fat -n |
| exFAT | partclone.exfat | fsck.exfat -n |

For each row:

1. Create a disposable filesystem with representative files, directories,
   permissions/metadata supported by that filesystem, and known checksums.
2. Ensure the source is in a safe, quiescent state. Record how Feclora prevents
   or detects mounted/in-use writes and filesystem inconsistency.
3. Capture a partition image and confirm the selected engine is the expected
   Partclone executable. Record artifact format, filesystem identifier, size
   and SHA-256.
4. Restore to an equal-or-larger disposable partition with compatible logical
   sector geometry. Confirm Feclora runs the declared read-only checker.
5. Mount the restored filesystem read-only where supported and compare file
   contents, directory structure and metadata that the filesystem preserves.
6. Repeat with the matching Partclone executable deliberately unavailable.
   Confirm capture selects raw dd explicitly, and raw restore verifies the
   destination by read-back rather than claiming filesystem-aware capture.
7. Repeat with an unknown FSTYPE and confirm the raw fallback is selected.
   A missing checker must reject a Partclone restore before target writes.
8. Record pass/fail/not-run separately for each filesystem and tool version.
   Unit tests and command-map coverage alone do not constitute acceptance.

Do not mark a filesystem supported for a release until its real capture/restore
round trip and integrity checks have passed on the target runtime.

## 8. Btrfs subvolume and snapshot discovery acceptance

Run this check in a disposable VM with a Btrfs filesystem already mounted and
containing at least one ordinary subvolume and one snapshot. Feclora discovery
must not mount, unmount, create, delete or otherwise modify Btrfs objects.

1. Record the filesystem UUID, mounted target, subvolume UUIDs and parent UUIDs
   using the native Btrfs tools as the independent reference.
2. Run Feclora storage inventory and confirm it reports each already-mounted
   Btrfs target, subvolume ID, UUID, path and parent UUID.
3. Confirm ordinary subvolumes with no parent UUID are classified as
   subvolumes, and snapshot descendants with a parent UUID are classified as snapshots.
   Received UUID provenance is recorded separately and must not, by itself,
   classify a received subvolume as a snapshot. Names alone must not determine
   snapshot status.
4. Repeat with a nested Btrfs mount and confirm it is inventoried separately.
5. Repeat without btrfs-progs or findmnt available and confirm the subvolume
   scan reports unavailable rather than guessing.
6. Confirm the operation is read-only and bounded; no mount or filesystem
   mutation command is issued. Record tool versions and the inventory output.

Mark not run until exercised against a real mounted Btrfs filesystem. This
inventory does not establish that snapshot capture or restore is supported.

## 7. BitTorrent distribution acceptance

BitTorrent is a first-class artifact-distribution transport at the same priority
as the other remote transports, not a writable repository provider. This
procedure applies after a maintained client implementation has been integrated.

1. Publish an immutable test artifact and its manifest through the normal
   trusted repository workflow; record the expected manifest digest.
2. Distribute the torrent metadata through an authenticated control channel.
   Do not treat tracker/peer metadata or successful download completion as
   authenticity.
3. Download on disposable Clients, including a run with a disconnected peer
   and a deliberately incomplete transfer.
4. Verify the manifest using the configured independent trust mechanism and
   verify every artifact's exact size and SHA-256 before making it available
   to a restore job.
5. Confirm the artifact is bound to the intended authorized job/profile and
   that an altered manifest, substituted artifact or replayed authorization
   is rejected before destructive I/O.
6. Test cancellation, temporary-file cleanup, bandwidth limits, peer/network
   restrictions, seeding policy and shutdown behavior.
7. Record client implementation/version, peer topology, transfer result and
   verification outcome. Mark not run until BitTorrent support is implemented.
