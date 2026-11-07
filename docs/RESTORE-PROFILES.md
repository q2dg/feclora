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
