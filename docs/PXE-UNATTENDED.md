# PXE Live and unattended answer files

## Intended operating model

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin Client, installer, or per-machine
provisioning workflow.

The PXE Server publishes the Live kernel, initramfs and squashfs through
Caddy. The existing interactive iPXE entry boots that Live payload and opens
the normal Feclora Cockpit interface. The answer-specific unattended entry first submits the iPXE MAC address to
a loopback admission service behind Caddy. Only an admitted MAC can retrieve
the job-specific boot script, which boots the same payload and passes the job
UUID plus the single answer URL as kernel parameters. A conditional Live
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
generated job UUID. It also publishes an iPXE admission wrapper and a separate
job-specific boot script. The boot script is available only through the
admission endpoint, not through Caddy's static file server.

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

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Security boundary

An answer file can authorize a destructive operation, so it must not be
treated as harmless configuration. It is published only after administrator
action through Cockpit, is scoped to one generated job UUID, and can currently
be revoked explicitly from the same Cockpit form. A new PXE session clears
stale published answer directories. Successful explicit deployment-job
cancellation revokes its answer. Answers do not expire automatically and can
be reused until revoked or cleared by a new PXE session. Clients validate the
schema and repository integrity metadata before any write. For this deployment, the operator explicitly chooses to trust the answer
served by the configured HTTP server. This is an operational trust assumption,
not cryptographic authenticity: an attacker able to modify HTTP traffic or the
server's published file can alter the instructions. Feclora does not add a
signature or transport-encryption layer to this HTTP answer workflow, nor does
it add per-client identity. Optional age encryption protects image artifacts,
not the answer JSON or HTTP transport.

The PXE Server registers the MAC address supplied by iPXE on the first
unattended boot request. Cockpit configures a maximum number of distinct MAC
addresses, a serving-time deadline, or both. Repeated requests from a MAC
already registered do not consume another client slot. When the client cap is
reached, new MAC addresses are refused; after the time deadline, all admission
and boot-script requests are refused. The ledger is root-owned and persists
for the lifetime of the PXE session. This is an operational admission limit,
not authentication: a client can spoof a MAC address. The admission gate does
not stop an already-running restore, invalidate a boot script already
retrieved by a client, or revoke the JSON answer file itself. The JSON answer
URL remains a public job-scoped locator until explicit revocation or stale
session cleanup; the MAC limit is an operational admission control, not a
security boundary.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Provider support status

The answer schema accepts URL schemes for SSHFS, SMB/CIFS, NFS, WebDAV,
HTTP(S) and S3. Only NFS is currently connected to PXE restore execution;
all other schemes fail closed until their Live provider adapters exist. Current repository support and
limitations are tracked in `REMOTE-REPOSITORIES.md`; WebDAV and S3
are not yet complete provider workflows. NVMe-oF is not a repository URL or PXE file provider.

## Current status and acceptance

- [x] Stage the same Fedora Live kernel, initramfs and squashfs for iPXE.
- [x] Provide interactive Live boot through iPXE.
- [x] Define and validate a bounded, data-only answer-file schema.
- [x] Publish an iPXE MAC-admission wrapper and a separate job-specific boot
      script; serve the latter only after the Server has registered the MAC.
- [x] Add a Live boot-time HTTP answer downloader and schema validator; store the
      validated JSON in the root-only Live runtime directory.
- [x] Connect the NFS repository adapter, unique WWN/serial target resolution,
      pre-write identity revalidation and existing whole-disk restore engine.
- [ ] Add SSHFS, SMB/CIFS, HTTP(S), WebDAV and S3 provider adapters
      plus credential_ref resolution.
- [x] Add one Cockpit JSON answer-file upload control; the repository URL is
      taken directly from the JSON document.
- [x] Validate and atomically publish/revoke job-scoped JSON files through Caddy.
- [x] Register unique iPXE MAC addresses in a persistent Server-side admission ledger; enforce configurable distinct-client and/or elapsed-time limits, and deny direct static access to the boot script.
- [x] Clear stale answer files and handoff scripts when a new PXE session starts.
- [x] Keep answer files reusable; explicit revocation and stale-session cleanup remain available. Successful deployment-job cancellation revokes its published answer.
- [x] Connect NFS URL to a read-only Live mount for whole-disk restore.
- [x] Support age symmetric decryption with one-shot Cockpit passphrase handoff on the Live client.
- [x] Support symmetric age passphrase encryption for whole-disk capture through Cockpit; partition and logical-volume capture remain recipient-based.
- [ ] Connect remaining repository URL schemes to provider and credential facilities.
- [x] Implement exact whole-disk target resolution, pre-write revalidation and
      execution through the existing verified whole-disk restore engine for NFS.
- [ ] Add other repository providers and lifecycle support.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Validate BIOS and UEFI PXE boot, Caddy publication/revocation, wrong or
      tampered answer files, wrong age passphrase, repository outage, ambiguous
      targets, target swaps, interruption and real restore hardware.

The NFS whole-disk software path, age passphrase handoff and MAC-based PXE
admission gate are connected and covered by automated tests. The complete path
has not yet been accepted on BIOS/UEFI PXE hardware; no production-ready
end-to-end claim is made.
