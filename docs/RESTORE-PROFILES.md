# Restore profiles

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

Profiles contain choices only. They must never contain age identity contents, private minisign keys, passwords, TLS private keys, or other secret material. The caller supplies credentials through a separate protected mechanism.

## Execution modes

- **interactive:** load the choices but ask the operator before destructive actions.
- **confirm:** perform preflight automatically and require a final typed confirmation before writing.
- **unattended:** require an authenticated profile and image manifest verified against an independently configured trust anchor, a timezone-qualified expiry, a single-use profile, exact stable target identity matching, and mandatory post-write verification. `minisign` is one optional signature implementation, not a product-wide dependency. The current executor is minisign-specific; replacing that hard dependency with a configurable trust/verifier interface is outstanding. A failed or incomplete preflight must stop before the first write.

The signature sidecar is named PROFILE.json.minisig. The trusted public key is configured outside the profile. For a standalone local invocation, the profile ID is recorded in the configured consumption ledger before the first destructive write. For PXE fleet jobs, replay protection belongs to the authenticated Server deployment-session journal and job state; the ephemeral Client Live session does not need a persistent local ledger. Until profile verification, PXE handoff and the Server/Client restore orchestrator are integrated end to end, the profile model is not an unattended PXE execution switch.

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
that it cannot reserve extents. This function performs no activation, write,
LV creation or restore; it is not yet connected to the restore executor or
Cockpit workflow.

The profile model and unattended whole-disk executor are implemented in src/feclora/storage/restore_profile.py and src/feclora/storage/profile_executor.py. They strictly validate schema fields, reject duplicate JSON keys and path traversal, match WWN/serial identities, verify minisign signatures, and atomically consume single-use authorization immediately before the first write. **Current limitation:** this executor currently requires minisign for profile and image authentication. The project policy is that minisign must remain optional; a configurable verifier/trust interface (with an equally strong alternative authentication path) is still required before unattended restore can satisfy that policy without minisign. UI-based profile authoring, automatic startup/systemd enablement and proportional layout execution remain pending.


## Running an unattended disk restore

The Live image installs the `feclora-restore-profile` command. For standalone CLI use, store the profile, image repository, trust keys and audit files on explicitly selected storage available during the Live session. The Live home directory and logs are ephemeral by design. The CLI's local consumption ledger protects that invocation; PXE fleet replay protection must be maintained by the authenticated Server deployment session, not by requiring a persistent Client Live disk.
The profile and image each need independently authenticated metadata. The current implementation requires separate detached minisign signatures and trusted public keys; this is an implementation-specific limitation, not a product-wide dependency. The target design must support another configured verifier so minisign remains optional.

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
profile, image, trust public keys and signatures there:

```sh
mkdir -p /mnt/restore-media/{profiles,trust,images,audit}
```

Sign the profile and the image manifest with the appropriate private keys on
a trusted preparation machine. Keep those private keys off the Live image.
Then invoke:

```sh
feclora-restore-profile \
  --profile /mnt/restore-media/profiles/lab.json \
  --profile-trusted-key /mnt/restore-media/trust/profile.pub \
  --image-trusted-key /mnt/restore-media/trust/images.pub \
  --repository /mnt/restore-media/images \
  --consumption-ledger /mnt/restore-media/audit/consumed-profiles.jsonl \
  --operation-log /mnt/restore-media/audit/operations.jsonl
```

For images encrypted with the optional age integration, additionally pass `--age-identity` with a protected
identity file supplied outside the profile. Use a Linux filesystem with POSIX ownership, permissions, locking and hard-link support (for example ext4, XFS or Btrfs); FAT/exFAT volumes may not provide the required semantics. The standalone CLI currently verifies that its consumption ledger and operation journal reside on a dedicated persistent mounted filesystem (not the Live overlay, tmpfs or root filesystem). This CLI constraint does not define the PXE architecture: PXE jobs use the Server's session-scoped journal and never require a persistent Client Live filesystem. It rechecks the WWN and serial immediately
before writing, after artifact and target preflight. It atomically consumes
the profile ID in the durable ledger at that same pre-write boundary. A consumed profile cannot be replayed from the same persistent
ledger, including after a reboot, interrupted or failed write. If the ledger
volume is unavailable, unmounted, corrupt or not writable, execution stops
before the disk write. The disk restore still performs its own
artifact verification, target safety checks, exact confirmation gate,
streaming write and read-back SHA-256 verification.

The current unattended executor supports whole-disk images with the
`preserve` layout policy. It rejects `proportional` rather than silently
pretending to resize partitions. The Local rescue TUI can create and sign unattended profiles. Automatic startup scheduling/systemd enablement is not enabled by default; an operator must explicitly configure it after mounting persistent profile, image, trust and audit storage.


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
FECLORA_PROFILE_TRUSTED_KEY=/mnt/restore-media/trust/profile.pub
FECLORA_IMAGE_TRUSTED_KEY=/mnt/restore-media/trust/images.pub
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

   Ensure the profile, image manifest, detached signatures, public keys,
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
