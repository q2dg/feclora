# ADR 0011: Secret Service for interactive secrets and systemd credentials for Server jobs

- Status: Accepted
- Date: 2026-11-10

## Context

Feclora runs in two materially different security contexts:

1. An operator interacts with Cockpit through an authenticated user session.
2. Privileged Server and Client workers run as root-owned systemd services and
   must continue after Cockpit disconnects or the operator logs out.

Fedora 45 provides `oo7-daemon`, which implements the freedesktop Secret
Service D-Bus API. It is a user-session service. It is appropriate for
interactive applications that can use the operator's D-Bus session and
unlocked keyring. It is not a machine-wide secret broker and must not become a
runtime dependency of root-owned unattended jobs.

systemd provides encrypted credentials through `systemd-creds` and
`LoadCredentialEncrypted=`. The encrypted payload is bound to the local
system credential key and, when available/configured, TPM2. systemd decrypts
the payload for the consuming service at activation and exposes it in that
service's private credential directory.

## Decision

- Use `oo7-daemon` / Secret Service only for interactive operator-session
  secret management where a real user bus and keyring-unlock lifecycle exist.
  Cockpit JavaScript must never access D-Bus secrets directly or carry secret
  values in API requests, browser storage, logs or journals.
- Use systemd encrypted credentials for credentials consumed by persistent
  root-owned Server/Client services. Each service receives only the specific
  credentials it needs through `LoadCredentialEncrypted=`.
- Do not pass systemd credential plaintext through command-line arguments,
  environment variables, unit-file literals, journals or Cockpit. Consumers
  read the private `$CREDENTIALS_DIRECTORY` files.
- Do not assume that a Cockpit user's Secret Service collection is accessible
  to a root service, or that it remains unlocked after logout/reboot.
- Keep the existing root-owned plaintext credential store only as a temporary
  compatibility mechanism. Migrate repository mounts and services before
  removing it; fail closed if a required credential is unavailable.
- Provisioning must use systemd's supported encryption interface. Do not
  implement a parallel encryption format or silently fall back to plaintext
  when systemd credential encryption is unavailable.

## Consequences

- The first implementation step is
  `feclora.storage.systemd_credential_store.SystemdCredentialStore`, which
  stores encrypted blobs under `/etc/credstore.encrypted/feclora`.
- This store is not yet connected to repository mount lifecycles or Cockpit.
  Per-repository systemd units (or equivalent service-scoped consumers) must
  be introduced before encrypted credentials can replace current mount-time
  credential files.
- Existing repository definitions and the local credential CLI remain
  compatibility paths during migration; their continued presence is not the
  target architecture.
- Tests must cover encryption invocation, create-only semantics, atomic
  replacement, safe metadata listing, permission/symlink rejection, missing
  systemd support and service-level credential isolation.
- Hardware-bound encryption depends on the host's systemd credential key and
  TPM configuration. Backups/recovery must account for loss or replacement
  of the original host/TPM; encrypted blobs must not be assumed portable.
