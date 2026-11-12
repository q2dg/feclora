# PXE Live and unattended answer files

## Intended operating model

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin Client, installer, or per-machine
provisioning workflow.

The PXE Server publishes the Live kernel, initramfs and squashfs through
Caddy. The existing interactive iPXE entry boots that Live payload and opens
the normal Feclora Cockpit interface. The answer-specific unattended entry boots the same payload and passes the
job UUID plus the single answer URL as kernel parameters. A conditional Live
systemd service downloads and validates the JSON; for NFS answers it then
runs the connected whole-disk restore path.

There is no per-client USB, identity medium, certificate, private key,
enrollment bundle or manual identity provisioning in this model. The PXE
client must not mount or look for `FECLORA-CLIENT` media.

## Deployment preparation

The Cockpit Server setup provides a single file input for the prewritten JSON
answer. The `repository_url` field inside that JSON identifies the image
repository; there is no second repository-URL field in Cockpit. The Server
validates the document and publishes it through Caddy over HTTP under a
generated job UUID. It also publishes an answer-specific iPXE script containing
the job UUID and the answer URL.

The PXE Server does not host or copy the image repository. It serves the Live
boot assets and the answer JSON. Credentials are not embedded in repository
URLs or the answer document; `credential_ref` is an opaque reference to
credentials managed separately by Feclora.

## Answer document, version 1

The first supported answer schema is deliberately data-only JSON. It contains
no shell commands, Python, arbitrary command-line arguments, local
`/dev/...` paths, usernames, passwords, private keys or certificates.

```json
{
  "schema_version": 1,
  "operation": "restore",
  "image_id": "fedora-workstation",
  "repository_url": "nfs://images.example.net/exports/feclora",
  "target": {
    "wwn": "0x5000abcd1234",
    "serial": null
  },
  "confirm_destructive": true,
  "start": true
}
```

The target is selected by stable hardware identity (WWN and/or serial), never
by a hard-coded device path. The Live client resolves exactly one matching whole disk from its current
inventory and rechecks that identity immediately before writing. Missing or
ambiguous matches fail closed.

The schema validator is implemented in `feclora.network.pxe_answer`. It
rejects duplicate JSON keys, unknown fields, malformed repository URLs,
embedded URL credentials, missing stable target selectors, and documents
which do not explicitly confirm destructive restore and automatic start.
The validator and server-side publication path are implemented. Cockpit exposes
one JSON file input; `repository_url` is read from that JSON, with no duplicate
repository field. The API publishes the validated JSON atomically through Caddy
over HTTP. No minisign, detached signature or per-client identity is involved. Optional age symmetric encryption is supported; the passphrase is entered on the Live client through Cockpit and is not included in the JSON. Cockpit can explicitly revoke the published
answer and its iPXE script by job UUID. A new PXE session also clears stale
answer files and handoff scripts. Answer revocation is not yet connected to deployment-job cancellation/expiry.

## Security boundary

An answer file can authorize a destructive operation, so it must not be
treated as harmless configuration. It is published only after administrator
action through Cockpit, is scoped to one generated job UUID, and can currently
be revoked explicitly from the same Cockpit form. A new PXE session clears
stale published answer directories. Automatic removal when a deployment job
expires or is cancelled is not implemented yet. Clients must validate its
schema and repository integrity metadata before any write. For this deployment, the operator explicitly chooses to trust the answer
served by the configured HTTP server. This is an operational trust assumption,
not cryptographic authenticity: an attacker able to modify HTTP traffic or the
server's published file can alter the instructions. Feclora does not add a
signature or transport-encryption layer to this HTTP answer workflow, nor does
it add per-client identity. Optional age encryption protects image artifacts,
not the answer JSON or HTTP transport.

The Live HTTP downloader and schema validation service are conditionally
started for unattended PXE kernel parameters. The first connected restore
provider is NFS: Live mounts it read-only, resolves exactly one whole disk by
WWN/serial, validates the image manifest and artifact digest, and calls the
existing whole-disk restore engine. Artifacts may be unencrypted or age-encrypted
with a symmetric passphrase. This PXE passphrase path applies only to age
passphrase-encrypted artifacts; recipient-encrypted age artifacts require an
identity and are not unlocked by this flow. The current capture UI still creates
recipient-based age artifacts, so creating symmetric-passphrase image sets
through Cockpit remains a follow-up. When a supported artifact is encrypted,
the restore worker waits for the operator to enter the passphrase in Cockpit on
that Live client.
Cockpit submits it once through the privileged local API; it is held briefly in
a root-only 0600 file under /run, consumed and unlinked, and is not placed in
the answer JSON, kernel command line, URL, environment or logs. The Live client
uses age's passphrase prompt through a pseudo-terminal and stages authenticated
plaintext in a private temporary file before writing the target. A wrong
passphrase or failed age authentication aborts before the first write. PXE
does not use minisign. The engine rechecks the target immediately before
writing and performs read-back verification. Other repository schemes,
credential references, cross-reboot expiry/replay controls and physical
hardware acceptance remain outstanding. The job UUID is consumed
atomically immediately before the first write to prevent a service restart from
replaying it during the same Live session; the Live filesystem is ephemeral,
so this is not a cross-reboot replay ledger. Do not describe unattended PXE as complete until those
pieces are connected and tested.

## Provider support status

The answer schema accepts URL schemes for SSHFS, SFTP, SMB/CIFS, NFS, WebDAV,
HTTP(S) and BitTorrent. Only NFS is currently connected to PXE restore execution;
all other schemes fail closed until their Live provider adapters exist. Current repository support and
limitations are tracked in `REMOTE-REPOSITORIES.md`; WebDAV and BitTorrent
are not yet complete provider/transport workflows.

## Current status and acceptance

- [x] Stage the same Fedora Live kernel, initramfs and squashfs for iPXE.
- [x] Provide interactive Live boot through iPXE.
- [x] Define and validate a bounded, data-only answer-file schema.
- [x] Publish an answer-specific iPXE handoff that boots the same Live payload
      and passes only the answer job UUID and single answer URL.
- [x] Add a Live boot-time HTTP answer downloader and schema validator; store the
      validated JSON in the root-only Live runtime directory.
- [x] Connect the NFS repository adapter, unique WWN/serial target resolution,
      pre-write identity revalidation and existing whole-disk restore engine.
- [ ] Add SSHFS, SFTP, SMB/CIFS, HTTP(S), WebDAV and BitTorrent provider adapters
      plus credential_ref resolution.
- [x] Add one Cockpit JSON answer-file upload control; the repository URL is
      taken directly from the JSON document.
- [x] Validate and atomically publish/revoke job-scoped JSON files through Caddy.
- [x] Clear stale answer files and handoff scripts when a new PXE session starts.
- [x] Consume each answer job UUID atomically immediately before the first write
      to prevent replay during the current Live session.
- [ ] Add cross-reboot expiry/replay protection and tie revocation to deployment-job cancellation/expiry.
- [x] Connect NFS URL to a read-only Live mount for whole-disk restore.
- [x] Support age symmetric decryption with one-shot Cockpit passphrase handoff on the Live client.
- [ ] Add Cockpit image-capture support for symmetric age passphrases; current capture remains recipient-based.
- [ ] Connect remaining repository URL schemes to provider and credential facilities.
- [x] Implement exact whole-disk target resolution, pre-write revalidation and
      execution through the existing verified whole-disk restore engine for NFS.
- [ ] Add other repository providers and lifecycle/replay controls.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Validate BIOS and UEFI PXE boot, Caddy publication/revocation, wrong or
      tampered answer files, wrong age passphrase, repository outage, ambiguous
      targets, target swaps, interruption and real restore hardware.

The NFS whole-disk software path and age passphrase handoff are connected in
code, but the new path has not yet been executed in tests or on PXE hardware;
no production-ready end-to-end claim is made.
