# PXE Live and unattended answer files

## Intended operating model

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin Client, installer, or per-machine
provisioning workflow.

The PXE Server publishes the Live kernel, initramfs and squashfs through
Caddy. The existing interactive iPXE entry boots that Live payload and opens
the normal Feclora Cockpit interface. The unattended entry must boot the same
payload and then fetch one deployment answer document from the PXE Server's
Caddy HTTP endpoint.

There is no per-client USB, identity medium, certificate, private key,
enrollment bundle or manual identity provisioning in this model. The PXE
client must not mount or look for `FECLORA-CLIENT` media.

## Deployment preparation

The Cockpit Server deployment form is intended to collect:

1. The image repository URL. This identifies external image storage and is
   independent of the PXE Server. The repository may be provided by SSHFS,
   SFTP, SMB/CIFS, NFS, WebDAV or BitTorrent, subject to the provider support
   matrix in `REMOTE-REPOSITORIES.md`.
2. The answer document, uploaded by the operator as a file in the same form.
   Feclora validates its schema and publishes the accepted document under a
   job-scoped name in the Caddy document root.
3. The PXE boot configuration and selected deployment clients/target policy.

The PXE Server does not host or copy the image repository. It only serves the
Live boot assets and the answer document. Credentials are not embedded in
repository URLs or the answer document; they are selected separately from
Feclora's protected credential inventory where the chosen provider needs
authentication.

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
The validator is a building block; it is not yet the complete PXE download,
repository-mount and restore execution path.

## Security boundary

An answer file can authorize a destructive operation, so it must not be
treated as harmless configuration. It must be published only by an
administrator through Cockpit, be scoped to one deployment, and be removed
when that deployment expires or is cancelled. Clients must validate its
schema and repository integrity metadata before any write. A plain HTTP
answer file is vulnerable to modification by an attacker on the PXE network;
production unattended writes therefore require a trusted integrity mechanism
for the answer document (for example, a detached signature checked against a
public key already trusted by the Feclora Live image). Merely downloading the
document or knowing its URL is not sufficient authorization.

The Server-side answer-file upload/publishing form, the signed download
handoff, the Live Client answer downloader, repository URL adapters and the
end-to-end no-identity execution flow remain implementation work. Do not
describe unattended PXE as complete until those pieces are connected and
tested.

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
- [ ] Add a Live boot-time answer-file downloader and client-side signature verifier.
- [ ] Add the deployment-form repository URL and answer-file upload controls.
- [ ] Publish per-job answer documents through Caddy and revoke them on job
      cancellation/expiry.
- [ ] Connect repository URL schemes to the existing remote repository
      credential and mount/transfer facilities.
- [ ] Implement target resolution, pre-write revalidation and unattended
      execution for the supported operation types.
- [ ] Add an answer integrity mechanism trusted by the Live image.
- [ ] Validate BIOS and UEFI PXE boot, Caddy publication/revocation, wrong or
      tampered answer files, missing credentials, repository outage, ambiguous
      targets, target swaps, interruption and real restore hardware.

No hardware acceptance or end-to-end unattended answer-file restore is
claimed by this document.
