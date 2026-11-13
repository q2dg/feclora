# PXE Live and unattended answer files

## Intended operating model

For the common ISO/PXE answer-file contract and ISO boot configuration, see
[UNATTENDED-RESTORE.md](UNATTENDED-RESTORE.md).

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin Client, installer, or per-machine
provisioning workflow.

The PXE Server publishes only the Live kernel, initramfs and squashfs through
Caddy. It does not proxy storage access or participate in restoration after
boot. The iPXE entry starts the same Feclora Live image as the ISO. An
unattended PXE boot passes the answer URL through the kernel command line; a
conditional Live systemd service downloads and validates it. ISO boots use
the same service and answer schema by adding the generic
feclora.unattended_url kernel argument with the Caddy answer URL. Both routes
therefore enter the same Live restore client; only the mechanism that supplies
the URL differs.

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

The PXE Server does not host, copy, mount or proxy the image repository. It
serves the Live boot assets and the answer JSON only. The Live client is
responsible for connecting to remote storage using Feclora's normal repository
configuration and credential handling. The current unattended answer adapter
still supports only NFS and credential-free HTTPS; integration with the full
Feclora repository manager (including SSHFS, SMB/CIFS and private S3) remains
work to do. Do not send repository credentials in the answer file or introduce
per-client authentication.

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

ISO and PXE Live clients run the same Feclora application and access
repositories directly, using the normal client-side repository manager and
its protected credential storage. The PXE Server is not a storage gateway.
Do not add per-client certificates, private keys, enrollment, bearer tokens
or client-specific credentials. The answer file contains repository selection
and restore parameters only, never passwords, keys or credential-bearing URLs.
The current unattended PXE adapter has not yet been unified with the complete
repository manager: NFS and credential-free HTTPS work today, while SSHFS,
SMB/CIFS and private S3 need integration with the existing Feclora client-side
repository mechanisms.

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

The unattended answer adapter currently connects NFS and credential-free HTTPS.
HTTPS uses the same object-key layout as Feclora's S3 adapter and verifies
TLS, byte count and SHA-256 before restore. This is a limitation of the current
PXE-specific adapter, not a desired architectural restriction: the next
integration step is to resolve the selected repository through Feclora's
existing client-side repository managers so ISO and PXE unattended restores
support the same configured providers and credentials. Until that work is
implemented and tested, SSHFS, SMB/CIFS and private S3 must fail closed in the
unattended adapter. HTTP repository downloads are not accepted.

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
- [ ] Unify unattended repository resolution with Feclora's existing client-side repository managers for NFS, SSHFS, SMB/CIFS and S3; keep credentials in the normal protected Live configuration and never put secrets in the answer file.
- [x] Implement exact whole-disk target resolution, pre-write revalidation and
      execution through the existing verified whole-disk restore engine for NFS and HTTPS.
- [ ] Add unattended tests for the full repository-manager path, including private S3, SSHFS and SMB/CIFS; keep unsupported schemes fail-closed until implemented and tested.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Add automated tests for tampered answers, wrong age passphrase, HTTPS redirect/size/checksum failures, repository errors, ambiguous targets, target swaps and interrupted staging/restore. BIOS/UEFI boot, Caddy against real networks and physical restore are optional operator acceptance, not software completion gates.

Each Live PXE restore writes start, progress and terminal events to
`/var/lib/feclora/pxe/operations.jsonl`. Cockpit's local Operation history
merges this journal with durable local operations and marks stale in-progress
entries interrupted after the originating process exits. PXE history entries
are read-only in Cockpit; the identity-free Client does not send authenticated
results to the Server.

The NFS and credential-free HTTPS whole-disk software paths, age passphrase handoff and MAC-based PXE admission gate are connected. Automated software tests are the release gate; BIOS/UEFI PXE boot and physical restore remain optional operator acceptance.
