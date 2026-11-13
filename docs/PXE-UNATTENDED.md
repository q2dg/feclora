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
systemd service downloads and validates the JSON; it then runs the connected whole-disk restore path using either a read-only NFS mount or a verified HTTPS object-set staging directory.

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
URLs or the answer document. The identity-free Live client currently supports
NFS and credential-free HTTPS only; `credential_ref` is rejected until a
secure client-side credential provisioning flow exists.

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

The PXE Server can register the MAC address supplied by iPXE on the first
unattended boot request. In Cockpit, the administrator may configure a maximum
number of distinct MAC addresses, a serving-time deadline, or both. Both fields
are empty by default: no client-count or time limit is imposed unless the
administrator explicitly enters one. Repeated requests from a MAC already
registered do not consume another client slot. When a configured client cap
is reached, new MAC addresses are refused; after a configured time deadline,
all admission and boot-script requests are refused. The ledger is root-owned
and persists for the lifetime of the PXE session. This is an operational
admission limit, not authentication: a client can spoof a MAC address. The admission gate does
not stop an already-running restore, invalidate a boot script already
retrieved by a client, or revoke the JSON answer file itself. The JSON answer
URL remains a public job-scoped locator until explicit revocation or stale
session cleanup; the MAC limit is an operational admission control, not a
security boundary.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Credential and result model

PXE Live clients remain identity-free. Do not add per-client certificates,
private keys, enrollment, bearer tokens or client-specific credentials to enable
private repositories or report results. The Server is the only component that
holds repository credentials. The intended provider design is a Server-side,
job-scoped, read-only repository view: the Server leases and mounts/accesses
the selected private S3, SSHFS or SMB/CIFS repository using its existing
root-managed credentials, then exposes only the selected image artifacts to
Live over the existing PXE HTTP service. The Live client downloads those
artifacts through the existing bounded HTTPS staging and SHA-256/size
verification path. No repository secret or credential-bearing URL is sent to
the client. This Server-side gateway is a design requirement, not an
implemented feature; private providers remain unavailable until it exists.

PXE result reporting must follow the same identity-free model. The Server may
accept bounded, job-scoped result reports without client authentication, but
must treat every field—including MAC address, operation status, progress and
timestamps—as untrusted client-supplied data. MAC addresses are correlation
hints only and must never be presented as authenticated identities. Server
reconciliation must validate the job and event schema, cap request/event sizes,
rate-limit or otherwise bound ingestion, and keep reported results distinct
from Server-observed state. No result-ingestion endpoint is implemented yet;
local Live operation history remains available in Cockpit on the PXE client.

## Provider support status

The answer schema accepts URL schemes for SSHFS, SMB/CIFS, NFS, HTTP(S) and S3. PXE restore currently connects NFS and credential-free HTTPS. HTTPS uses the same object-key layout as Feclora's S3 adapter: `<prefix>/<image_id>.manifest.json` and `<prefix>/<image_id>/<artifact filename>`. TLS certificate validation is enabled, redirects are rejected, and every artifact is size/SHA-256 verified before restore. A public S3 bucket or HTTPS object gateway can therefore be used through its HTTPS base prefix. Private S3, `s3://`, SSHFS and SMB/CIFS remain unavailable until a secure Live credential handoff is implemented; `credential_ref` fails closed. HTTP repository downloads are not accepted. Current repository support and limitations are tracked in `REMOTE-REPOSITORIES.md`.

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
- [x] Add a credential-free HTTPS object-set adapter with verified TLS, redirect rejection, bounded manifest/artifact downloads, local staging-capacity preflight and SHA-256/size verification; it supports public or externally pre-authorized S3-compatible object prefixes.
- [x] Add one Cockpit JSON answer-file upload control; the repository URL is
      taken directly from the JSON document.
- [x] Validate and atomically publish/revoke job-scoped JSON files through Caddy.
- [x] Register unique iPXE MAC addresses in a persistent Server-side admission ledger; enforce configurable distinct-client and/or elapsed-time limits, and deny direct static access to the boot script.
- [x] Clear stale answer files and handoff scripts when a new PXE session starts.
- [x] Keep answer files reusable; explicit revocation and stale-session cleanup remain available. Successful deployment-job cancellation revokes its published answer.
- [x] Connect NFS URL to a read-only Live mount and credential-free HTTPS object prefixes to whole-disk restore.
- [x] Support age symmetric decryption with one-shot Cockpit passphrase handoff on the Live client.
- [x] Support symmetric age passphrase encryption for whole-disk capture through Cockpit; partition and logical-volume capture remain recipient-based.
- [ ] Implement a Server-side, job-scoped read-only repository gateway for private S3, SSHFS and SMB/CIFS. Keep all repository credentials on the Server; never provision client identities or copy Server-bound systemd-creds blobs to Live.
- [x] Implement exact whole-disk target resolution, pre-write revalidation and
      execution through the existing verified whole-disk restore engine for NFS and HTTPS.
- [ ] Add private S3, SSHFS and SMB/CIFS through the Server-side read-only gateway; keep unsupported schemes fail-closed until the gateway is implemented and tested.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Add automated tests for tampered answers, wrong age passphrase, HTTPS redirect/size/checksum failures, repository errors, ambiguous targets, target swaps and interrupted staging/restore. BIOS/UEFI boot, Caddy against real networks and physical restore are optional operator acceptance, not software completion gates.

Each Live PXE restore writes start, progress and terminal events to
`/var/lib/feclora/pxe/operations.jsonl`. Cockpit's local Operation history
merges this journal with durable local operations and marks stale in-progress
entries interrupted after the originating process exits. PXE history entries
are read-only in Cockpit; the identity-free Client does not send authenticated
results to the Server.

The NFS and credential-free HTTPS whole-disk software paths, age passphrase handoff and MAC-based PXE admission gate are connected. Automated software tests are the release gate; BIOS/UEFI PXE boot and physical restore remain optional operator acceptance.
