# PXE Live and unattended answer files

## Intended operating model

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin Client, installer, or per-machine
provisioning workflow.

The PXE Server publishes the Live kernel, initramfs and squashfs through
Caddy. The existing interactive iPXE entry boots that Live payload and opens
the normal Feclora Cockpit interface. The answer-specific unattended entry boots the same payload and passes the
job UUID plus the single answer URL as kernel parameters. A Live boot-time
downloader must still be added to fetch and validate the JSON.

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
  "repository_url": "sftp://images.example.net/feclora",
  "target": {
    "wwn": "0x5000abcd1234",
    "serial": null
  },
  "confirm_destructive": true,
  "start": true,
  "credential_ref": "image-store"
}
```

The target is selected by stable hardware identity (WWN and/or serial), never
by a hard-coded device path. The Client must resolve exactly one matching
whole disk from its current inventory and recheck that identity immediately
before writing. Missing or ambiguous matches fail closed.

The schema validator is implemented in `feclora.network.pxe_answer`. It
rejects duplicate JSON keys, unknown fields, malformed repository URLs,
embedded URL credentials, missing stable target selectors, and documents
which do not explicitly confirm destructive restore and automatic start.
The validator and server-side publication path are implemented. Cockpit exposes
one JSON file input; `repository_url` is read from that JSON, with no duplicate
repository field. The API publishes the validated JSON atomically through Caddy
over HTTP. No age, minisign, detached signature or client identity is involved. Cockpit can explicitly revoke the published
answer and its iPXE script by job UUID. A new PXE session also clears stale
answer files and handoff scripts. This is not yet connected to cancellation/
expiry of a deployment job, and it is not yet the complete PXE download,
client-side verification, repository-mount or restore execution path.

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
signature, encryption layer or per-client identity to this workflow.

The Live Client answer downloader, repository URL adapters and the end-to-end
identity-free execution flow remain implementation work. Do not describe unattended PXE as complete until those
pieces are connected and tested.

## Provider support status

The answer schema accepts URL schemes for SSHFS, SFTP, SMB/CIFS, NFS, WebDAV,
HTTP(S) and BitTorrent. This is syntax validation only, not a claim that every
provider is implemented for PXE restores. Current repository support and
limitations are tracked in `REMOTE-REPOSITORIES.md`; WebDAV and BitTorrent
are not yet complete provider/transport workflows.

## Current status and acceptance

- [x] Stage the same Fedora Live kernel, initramfs and squashfs for iPXE.
- [x] Provide interactive Live boot through iPXE.
- [x] Define and validate a bounded, data-only answer-file schema.
- [x] Publish an answer-specific iPXE handoff that boots the same Live payload
      and passes only the answer job UUID and single answer URL.
- [ ] Add a Live boot-time answer-file downloader and schema validator.
- [x] Add one Cockpit JSON answer-file upload control; the repository URL is
      taken directly from the JSON document.
- [x] Validate and atomically publish/revoke job-scoped JSON files through Caddy.
- [x] Clear stale answer files and handoff scripts when a new PXE session starts.
- [ ] Tie answer revocation to deployment-job cancellation and expiry.
- [ ] Connect repository URL schemes to the existing remote repository
      credential and mount/transfer facilities.
- [ ] Implement target resolution, pre-write revalidation and unattended
      execution for the supported operation types.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Validate BIOS and UEFI PXE boot, Caddy publication/revocation, wrong or
      tampered answer files, missing credentials, repository outage, ambiguous
      targets, target swaps, interruption and real restore hardware.

No hardware acceptance or end-to-end unattended answer-file restore is
claimed by this document.
