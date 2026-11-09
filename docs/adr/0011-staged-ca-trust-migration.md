# ADR 0011: Staged deployment CA trust migration

- Status: Accepted design; implementation pending
- Date: 2026-11-09
- Scope: managed Server/Client mutual-TLS deployment identity

## Context

The managed PKI currently has one active deployment CA certificate at `/etc/feclora/pki/ca.crt`. The Server uses that trust anchor for Client authentication, and enrolled Clients install a single `ca.crt` and use it to authenticate the Server. Client enrollment and renewal bundles likewise carry one CA certificate. A Client renewal replaces its installed CA certificate and leaf certificate as one rollback-capable operation.

This is adequate for leaf renewal under the existing CA, but it is not a safe CA-rotation protocol. Replacing `ca.crt` before every enrolled endpoint trusts the replacement can strand control-plane connectivity. Switching the Server first can reject old Client certificates; switching Clients first can make them reject the old Server certificate. A single-CA runtime configuration cannot express the overlap required for a staged migration.

The current implementation must therefore not expose a one-step CA rotation action or overwrite the active CA as a shortcut.

## Decision

Implement CA rotation as an explicit, resumable, multi-phase migration. The old CA remains available until every required Server and Client trust consumer has been migrated and verified.

### Required phases

1. **Prepare**
   - Generate a new CA key and self-signed CA certificate in a new versioned, root-owned directory.
   - Never overwrite or rename the active CA files.
   - Validate CA constraints, key usage, validity window, key/certificate correspondence and SHA-256 fingerprint.
   - Persist a root-owned migration manifest with a random migration ID, old/new fingerprints, schema version, creation time and phase.
   - Do not activate the new CA for issuance or change any active TLS paths.

2. **Distribute dual trust**
   - Produce a signed or otherwise authenticated migration package containing only public old+new CA certificates and migration metadata; never export the new CA private key.
   - Add a Client-side trust-update operation that validates the package, verifies the expected Server identity and authenticated migration metadata, and atomically installs a CA bundle containing both anchors.
   - Preserve the existing Client leaf certificate, private key, age identity, MAC authorization and image-signing identity.
   - Record per-Client acknowledgement against the migration ID and both fingerprints.
   - Extend Server runtime trust to accept Client certificates chaining to either CA before any new-CA Client leaf is issued.

3. **Switch Server and issue new Client leaves**
   - Install the Server certificate/key signed by the new CA only after the Server trust bundle contains both CAs.
   - Retain the old Server leaf/key as a protected rollback artifact until the new identity has been validated.
   - Renew/reissue each Client leaf under the new CA using its existing locally-held private key and CSR workflow.
   - Require an authenticated acknowledgement after each Client has installed and validated its new leaf and dual trust.
   - Do not infer migration completion from package export or file-copy success alone.

4. **Verify convergence**
   - Check all configured and enrolled Client identities, including offline Clients, against the migration manifest.
   - Confirm the Server and every online Client authenticate successfully with the new CA and that all required Client leaves chain to it.
   - Keep the old CA trusted while any enrolled Client remains unacknowledged or is explicitly marked pending.
   - Report offline/pending identities distinctly; never silently drop them from the migration inventory.

5. **Retire old trust**
   - Require explicit, destructive confirmation and a complete convergence report.
   - Remove the old CA from active trust bundles only after the operator acknowledges the impact on offline Clients.
   - Preserve a protected, auditable recovery backup of old CA material according to the existing CA-backup policy.
   - Mark the migration retired; never automatically delete historical migration records or backups.

### Recovery and interruption

- Every phase transition must be atomic, persisted and idempotent for the migration ID.
- A restart must inspect the manifest and active files, then report the exact phase; it must not guess, silently advance, or regenerate key material.
- Rollback is allowed before old-trust retirement. Rollback must restore the previous Server leaf/key and trust configuration while retaining the migration record for audit.
- After old trust is retired, recovery is a separately confirmed forward-recovery operation; do not silently re-enable old trust.
- Corrupt manifests, fingerprint mismatches, unexpected files, symlinks, non-root-owned material or ambiguous partial installation must fail closed and require operator inspection.

## Implementation dependencies

1. Add versioned CA storage and strict certificate/key/manifest validation.
2. Generalize Server and Client TLS runtime configuration from a single CA path to an explicit trust-bundle path while retaining a backward-compatible migration path for existing installations.
3. Implement dual-CA TLS verification for both Server-side Client authentication and Client-side Server authentication.
4. Add Client trust-package import and acknowledgement; wire it through Cockpit allowlists and removable-media validation.
5. Add Server-side migration inventory, phase/status APIs and operator confirmations.
6. Add deterministic unit tests for every phase, interrupted writes, rollback, malformed packages, unknown/offline Clients and mixed old/new chains.
7. Document the manual removable-media sequence and acceptance procedure before enabling the operator workflow.

## Safety invariants

- Never replace the active CA key or certificate in place.
- Never transmit a CA private key to a Client or removable media.
- Never switch the Server leaf before dual trust is active on the Server.
- Never issue a new-CA Client leaf before the Server trusts both old and new Client chains.
- Never retire old trust while an enrolled Client is unaccounted for.
- Never claim live connectivity, systemd or hardware acceptance based only on unit tests.

## Consequences

CA rotation remains unavailable until the dependencies and phase-level tests above are implemented. Existing same-CA Server certificate renewal, Server keypair rotation, Client certificate renewal and encrypted CA backup remain separate workflows and must not be presented as CA rotation.
