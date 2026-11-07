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
- **unattended:** require a detached minisign signature verified against a separately configured trusted public key, a timezone-qualified expiry, a single-use profile, exact stable target identity matching, and mandatory post-write verification. A failed or incomplete preflight must stop before the first write.

The signature sidecar is named PROFILE.json.minisig. The trusted public key is configured outside the profile. The profile ID must be recorded in a persistent consumption ledger before the first destructive write so a single-use profile cannot be replayed. Until that ledger and the restore orchestrator are integrated, the profile model is a validation foundation, not an unattended execution switch.

## Layout policies

- **preserve:** retain source partition boundaries and leave additional target capacity unallocated, repairing secondary GPT metadata where required.
- **proportional:** redistribute partition capacity proportionally. This is not equivalent to merely editing GPT end sectors: moving or expanding partitions can overwrite subsequent data. It requires a partition-aware restore plan and filesystem-aware growth, with preflight validation for every partition/filesystem combination. The raw whole-disk clone path does not silently apply this policy.

The profile model and unattended whole-disk executor are implemented in src/feclora/storage/restore_profile.py and src/feclora/storage/profile_executor.py. They strictly validate schema fields, reject duplicate JSON keys and path traversal, match WWN/serial identities, verify minisign signatures, and atomically consume single-use authorization immediately before the first write. UI-based profile authoring, automatic startup/systemd enablement and proportional layout execution remain pending.


## Running an unattended disk restore

The Live image installs the `feclora-restore-profile` command. Store the
profile, image repository, trust keys and audit files on storage that remains
available to the Live session. The Live home directory and its logs may reside
on a volatile overlay and are not suitable as a replay ledger across reboots.
The profile and image each need their own detached minisign signature and
separately trusted public key.

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

For age-encrypted images, additionally pass `--age-identity` with a protected
identity file supplied outside the profile. The command verifies that the consumption ledger and operation
journal reside on a dedicated persistent mounted filesystem (not the Live
overlay, tmpfs or root filesystem). It rechecks the WWN and serial immediately
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
