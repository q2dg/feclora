---
layout: default
title: Restore profiles
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

![Illustrative restore-profile authorization workflow]({{ '/assets/mockups/restore-profile.svg' | relative_url }})

*Illustrative mockup — not a screenshot. The Cockpit profile flow requires a persistent filesystem repository and a single-use authorization.*

A restore profile records repeatable operator choices without embedding private keys or bypassing the storage safety checks in the restore engine.

## Profile contents

Schema version 1 stores:

- A UUID and human-readable name.
- A manifest filename confined to the configured image repository.
- A target selector bound to a disk WWN, serial number, or both. Device paths such as /dev/sdX are deliberately not accepted as stable identity.
- Execution mode: interactive, confirm, or unattended.
- Layout policy: preserve or proportional.
- Mandatory post-write verification.
- Optional success action: no action, reboot or poweroff.
- Optional expiry and single-use policy.

Profiles contain choices only. They must never contain age identity contents, passwords, TLS private keys, or other secret material. The caller supplies credentials through a separate protected mechanism.

## Execution modes

- **interactive:** load the choices but ask the operator before destructive actions.
- **confirm:** perform preflight automatically and require a final typed confirmation before writing.
- **unattended:** require a root-owned mode-0600 profile in a root-owned directory that is not group/other-writable, a timezone-qualified expiry, a single-use profile, exact stable target identity matching, and mandatory post-write verification. The local filesystem ownership boundary authorizes the profile; a failed or incomplete preflight must stop before the first write.

Unattended profile authorization is based on local root ownership and restrictive permissions. For a standalone local invocation, the profile ID is recorded in the configured consumption ledger before the first destructive write. For the existing Server-authenticated TLS Remote jobs, job correlation and result state belong to the Server deployment-session journal and job state; Clients are not authenticated individually. The identity-free PXE answer workflow is separate: it trusts the configured PXE HTTP server by operator choice, downloads a schema-validated JSON answer, and resolves the configured repository through the normal Live repository manager for whole-disk restore. PXE answer files are reusable until revoked; the answer-file client does not enforce expiry or single-use replay protection. Physical acceptance remains outstanding. The standalone profile executor is not currently an unattended PXE execution switch.

## Layout policies

- **preserve:** retain source partition boundaries and leave additional target capacity unallocated, repairing secondary GPT metadata where required.
- **proportional:** redistribute partition capacity proportionally. This is not equivalent to merely editing GPT end sectors: moving or expanding partitions can overwrite subsequent data. It requires a partition-aware restore plan and filesystem-aware growth, with preflight validation for every partition/filesystem combination. The raw whole-disk clone path does not silently apply this policy.

A separate read-only `preflight_logical_volume_restore()` primitive in
`profile_executor.py` validates an existing LV destination: LVM report
completeness, VG/PV health and membership, target LV identity and active
kernel major/minor mapping, capacity, mounted/read-only state, snapshot
relationships, and thin-pool health/data/metadata percentages, including a conservative estimate of free data capacity against the image size. It resolves
`/dev/VG/LV` versus `/dev/mapper/*` aliases only through a unique kernel
major/minor identity. Thin-pool allocation is dynamic, so the preflight warns
that it cannot reserve extents. Only linear and thin LVs are currently
accepted by the preflight; RAID, striped, cache, snapshot and unknown segment
layouts fail closed until their restore semantics are explicitly validated.
The preflight remains read-only; `logical_volume_restore.py` now invokes it
before and immediately before writing, then restores into the already active
LV. Raw images are read back and compared byte-for-byte; Partclone images are
checked with a filesystem-specific read-only checker. The local Cockpit
workflow exposes this operation. No LV/VG/PV creation, resizing, activation or
LVM metadata restoration is performed. Deployment-job LV restore remains
pending.

The profile model and unattended whole-disk executor are implemented in `src/feclora/storage/restore_profile.py` and `src/feclora/storage/profile_executor.py`. They strictly validate schema fields, reject duplicate JSON keys and path traversal, match WWN/serial identities, enforce root-owned local authorization and atomically consume single-use authorization immediately before the first write. Cockpit now creates, lists and explicitly executes single-use profiles through the durable local-operation worker. Profile files, the replay ledger and the operation audit are stored on the selected mounted persistent filesystem repository; root-overlay, root-filesystem and S3 storage are rejected. The boot-time systemd service remains disabled by default. Proportional layout execution remains unsupported for profiles.

## Running an unattended disk restore

The Live image installs the `feclora-restore-profile` command. For standalone CLI use, store the profile, image repository and audit files on explicitly selected storage available during the Live session. The Live home directory and logs are ephemeral by design. The CLI's local consumption ledger protects that standalone profile invocation. The separate PXE answer-file workflow does not use a consumption ledger.
Artifact SHA-256 digests provide integrity checks; authenticity relies on the protected local repository and authenticated transport. Unattended profile authorization relies on root ownership and restrictive filesystem permissions.

A profile JSON document has this shape (replace all example identities and
timestamps with values collected from the actual target):

```json
{
  "schema_version": 1,
  "profile_id": "12f7b67b-44e0-4d0b-a0b2-58b3d02c04e7",
  "name": "Lab restore",
  "image_manifest": "golden-image.manifest.json",
  "target": {
    "wwn": "0x5000c50012345678",
    "serial": "SN-001"
  },
  "execution_mode": "unattended",
  "layout_policy": "preserve",
  "verify_after_restore": true,
  "on_success": "none",
  "expires_at": "2030-01-01T00:00:00Z",
  "single_use": true
}
```

Create the directories on a mounted persistent filesystem, then copy the
profile, image and audit files there:

```sh
mkdir -p /mnt/restore-media/{profiles,trust,images,audit}
```

Create the profile as root in a root-owned directory that is not writable by group or other users. The profile is stored with mode 0600.

For images encrypted with the optional age integration, additionally pass `--age-identity` with a protected
identity file supplied outside the profile. Use a Linux filesystem with POSIX ownership, permissions, locking and hard-link support (for example ext4, XFS or Btrfs); FAT/exFAT volumes may not provide the required semantics. The standalone CLI currently verifies that its consumption ledger and operation journal reside on a dedicated persistent mounted filesystem (not the Live overlay, tmpfs or root filesystem). This CLI constraint does not define the PXE architecture: PXE jobs use the Server's session-scoped journal and never require a persistent Client Live filesystem. It rechecks the WWN and serial immediately
before writing, after artifact and target preflight. It atomically consumes
the profile ID in the durable ledger at that same pre-write boundary. A consumed profile cannot be replayed from the same persistent
ledger, including after a reboot, interrupted or failed write. If the ledger
volume is unavailable, unmounted, corrupt or not writable, execution stops
before the disk write. The disk restore still performs its own
artifact verification, target safety checks, exact confirmation gate,
streaming write and read-back SHA-256 verification.

The current unattended executor requires root-owned profile and parent-directory permissions and supports whole-disk images with the
`preserve` layout policy. It rejects `proportional` rather than silently
pretending to resize partitions. The Cockpit Restore profiles tab requires a mounted, verified, writable filesystem repository. It stores profiles in `.feclora/restore-profiles` and creates the replay ledger and operation journal in `.feclora/restore-audit` on that same persistent mount. It rejects local root-overlay storage and S3. The operator must type the exact `ERASE /dev/...` phrase to submit execution; the durable worker locks the selected target, the profile executor rechecks the WWN/serial binding and expiry, and the profile ID is atomically consumed immediately before the first write. A consumed profile is displayed as consumed and cannot be replayed from that repository ledger. The boot-time systemd service is not enabled by Cockpit and remains disabled by default. This standalone profile executor is not used by the PXE fleet workflow. The identity-free PXE answer workflow uses a shared JSON answer and WWN/serial target binding; it does not enroll or identify individual Clients. Automatic startup for this standalone profile executor remains disabled by default; an operator must explicitly configure it after mounting persistent profile, image and audit storage.


## Optional boot-time execution

The Live image installs `feclora-restore-profile.service` and its environment
wrapper, but the service is **disabled by default**. To enable it deliberately:

1. Mount the persistent restore medium at `/mnt/restore-media` during boot
   (for example through an explicit fstab entry). The service has
   `RequiresMountsFor=/mnt/restore-media`.
2. Create `/etc/feclora/restore-profile.env` as a root-owned file readable by
   the `feclora` group (mode 0640). It contains paths only, never key material:

```ini
FECLORA_PROFILE=/mnt/restore-media/profiles/lab.json
FECLORA_IMAGE_REPOSITORY=/mnt/restore-media/images
FECLORA_CONSUMPTION_LEDGER=/mnt/restore-media/audit/consumed-profiles.jsonl
FECLORA_OPERATION_LOG=/mnt/restore-media/audit/operations.jsonl
FECLORA_AGE_IDENTITY=
```

3. Create the environment directory and protect its configuration:

```sh
sudo install -d -o root -g feclora -m 0750 /etc/feclora
sudo chown -R feclora:feclora /mnt/restore-media
sudo chmod 0640 /etc/feclora/restore-profile.env
sudo chown root:feclora /etc/feclora/restore-profile.env
```

   Ensure the profile, image manifest,
   age identity (only if the image uses age), audit directory and mount are readable/writable
   as appropriate by the live `feclora` account.
4. Enable the service explicitly with
   `systemctl enable feclora-restore-profile.service`.

The unit runs before the interactive tty1 login to avoid racing the rescue
menu. It does not start DHCP, PXE or other network services. The service is
not enabled by the ISO build. The profile's persistent one-time ledger is the
replay barrier; if the same profile is attempted again, the executor exits
before writing. Disable the unit after the intended deployment if repeated
boot attempts are not wanted.


## Cockpit profile authoring

Open **Restore profiles** in Cockpit and select a mounted, verified,
writable filesystem repository. The repository must be backed by a dedicated
persistent mount; the root filesystem, Live overlay and S3 are rejected.
Select a RAW whole-disk image from that repository, choose a detected whole
disk exposing a WWN and/or serial number, name the profile and set a future
expiry. The API revalidates that the stable selector matches exactly one
currently detected whole disk and that the manifest is a matching whole-disk
image before atomically publishing a root-owned mode-0600 profile in the
root-owned mode-0700 `.feclora/restore-profiles` directory.

To execute, locate the profile in the list, verify the detected target path,
and type exactly `ERASE /dev/...` into its confirmation field. Cockpit submits
a durable local operation. The worker rechecks the profile, image repository,
expiry and WWN/serial target binding. The profile executor verifies that the
replay ledger and operation journal are on the same persistent mount, then
atomically consumes the profile immediately before the first disk write.
The existing disk restore engine performs artifact verification, target
safety checks, streaming write and read-back SHA-256 verification. A failed
preflight does not consume the profile; a failure after the first write does,
so the same authorization cannot be replayed against a partially written disk.

Saving or executing a profile does not enable
`feclora-restore-profile.service`; boot-time execution remains a separate
operator-managed choice. The Cockpit path supports filesystem-backed
repositories only, not S3. Proportional restore remains a separate interactive
operation and is not available through unattended profiles.
