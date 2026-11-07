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

The runtime model is implemented in src/feclora/storage/restore_profile.py. It strictly validates schema fields, rejects duplicate JSON keys and path traversal, matches WWN/serial identities, and verifies minisign signatures for unattended profiles. It does not yet execute profiles or consume their single-use authorization; those require integration with the restore UI, operation journal and executor.


## Running an unattended disk restore

The Live image installs the `feclora-restore-profile` command. A profile is
stored under `/home/feclora/profiles`; the profile and image each need their
own detached minisign signature and separately trusted public key.

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
  --profile /home/feclora/profiles/lab.json \
  --profile-trusted-key /etc/feclora/trust/profile.pub \
  --image-trusted-key /etc/feclora/trust/images.pub \
  --repository /home/feclora/images
```

For age-encrypted images, additionally pass `--age-identity` with a protected
identity file supplied outside the profile. The command rechecks the WWN and
serial immediately before writing, after artifact and target preflight. It
atomically consumes the profile ID in a durable ledger at that same
pre-write boundary. A consumed profile cannot be replayed, including after
an interrupted or failed write. The disk restore still performs its own
artifact verification, target safety checks, exact confirmation gate,
streaming write and read-back SHA-256 verification.

The current unattended executor supports whole-disk images with the
`preserve` layout policy. It rejects `proportional` rather than silently
pretending to resize partitions. Automatic startup scheduling/systemd
enablement and UI-based profile authoring are not enabled by default.
