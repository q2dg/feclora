---
layout: default
title: PXE Live and unattended answer files
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

# PXE Live and unattended answer files

## Intended operating model

For the common ISO/PXE answer-file contract and dynamic URL discovery, see
[UNATTENDED-RESTORE.md](UNATTENDED-RESTORE.md).

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin client, installer, or per-machine
provisioning workflow.

The Feclora PXE Server is the single deployment component containing DHCP,
Caddy and the services needed to distribute Live boot assets and publish
answer files. DHCP and Caddy are internal parts of this server, not external
dependencies. In authoritative/isolated DHCP mode, dnsmasq supplies private
DHCP option 224 with the stable Caddy URL
`/unattended-answer.json`; the ISO stays generic when the server address or
port changes. In ProxyDHCP mode, dnsmasq includes the locator in its
PXE-specific response, while a locally booted ISO also needs option 224 from
the upstream authoritative DHCP server. PXE iPXE handoff passes the
job-specific answer URL directly to the same Live client.

The PXE Server publishes the Live kernel, initramfs and squashfs and the
answer JSON through Caddy. It does not proxy storage access, mount remote
repositories, execute restoration, or receive operation logs, progress or
restore results. Both ISO and PXE enter the same Live answer-fetch service,
validator and restore client. The Live service checks the NetworkManager
DHCPv4 lease for option 224 on ISO boots and otherwise leaves interactive
boots unchanged.

There is no per-client USB, identity medium, certificate, private key,
enrollment bundle or manual identity provisioning in this model. Do not
require client authentication or use MAC addresses as authenticated identity.

## Deployment preparation

The Cockpit Server setup provides a single file input for the prewritten JSON
answer. The `repository_id` field inside that JSON selects a repository already
configured in the Live client's normal Feclora repository manager; there is no second repository-URL field in Cockpit. The Server
validates the document and publishes it through its Caddy service over HTTP
under a generated job UUID. It also publishes an iPXE admission wrapper and a
separate job-specific boot script. The boot script is available only through
the admission endpoint, not through Caddy's static file server.

The PXE Server does not host, copy, mount or proxy the image repository. It
serves the Live boot assets and the answer JSON only. The Live client is
responsible for connecting directly to external SSHFS, NFS, SMB/CIFS and S3
repositories using Feclora's normal client-side repository configuration and
protected credential handling. Do not send repository credentials in the
answer file or introduce per-client authentication.

## Answer document, version 2

The first supported answer schema is deliberately data-only JSON. It contains
no shell commands, Python, arbitrary command-line arguments, local
`/dev/...` paths, usernames, passwords, private keys or certificates.

```json
{
  "schema_version": 2,
  "operation": "restore",
  "image_id": "fedora-workstation",
  "repository_id": "nas-images",
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

## Repository and client model

ISO and PXE Live clients run the same Feclora application and access
repositories directly, using the normal client-side repository manager and
its protected credential storage. The PXE Server is not a storage gateway.
Do not add per-client certificates, private keys, enrollment, bearer tokens
or client-specific credentials. The answer file contains repository selection
and restore parameters only, never passwords, keys or credential-bearing URLs.
The unattended PXE adapter resolves the selected ID through the existing
client-side repository managers. SSHFS, NFS and SMB/CIFS use the normal managed
mount lifecycle and protected credentials; S3 uses the normal encrypted
credential store and object repository adapter. The PXE answer never contains
a URL, credential reference or secret.

PXE is only a boot transport. After Live starts, storage access and
restoration are performed by the Client itself. The PXE Server does not
receive operation logs, progress reports or restore results. Local operation
history remains on the Live Client; no client authentication or reporting
channel is required.

## Provider support status

The answer selects an existing repository by ID. The Live client uses the
same RemoteRepositoryManager for SSHFS, NFS and SMB/CIFS, including its normal
mount verification, usage lease and protected credential handling. S3 uses
S3RepositoryManager, its usage lease, encrypted credential store and normal
image-set download path. The PXE Server never accesses these repositories.

## Current status and acceptance

- [x] Stage the same Fedora Live kernel, initramfs and squashfs for iPXE.
- [x] Provide interactive Live boot through iPXE.
- [x] Define and validate a bounded, data-only answer-file schema.
- [x] Publish an iPXE MAC-admission wrapper and a separate job-specific boot
      script; serve the latter only after the Server has registered the MAC.
- [x] Add a Live boot-time HTTP answer downloader and schema validator; store the
      validated JSON in the root-only Live runtime directory.
- [x] Advertise the stable current-answer URL as DHCP option 224 in
      authoritative DHCP mode and the PXE-specific proxy response; discover it
      from the Live NetworkManager lease on ISO boots.
- [x] Resolve the repository ID using the normal managed repository managers, unique WWN/serial target resolution,
      pre-write identity revalidation and existing whole-disk restore engine.
- [x] Add one Cockpit JSON answer-file upload control; the repository ID is
      taken directly from the JSON document.
- [x] Validate and atomically publish/revoke job-scoped JSON files through Caddy.
- [x] Register unique iPXE MAC addresses in a persistent Server-side admission ledger; enforce configurable distinct-client and/or elapsed-time limits, and deny direct static access to the boot script.
- [x] Clear stale answer files and handoff scripts when a new PXE session starts.
- [x] Keep answer files reusable; explicit revocation and stale-session cleanup remain available. Successful deployment-job cancellation revokes its published answer.
- [x] Connect the normal SSHFS, NFS, SMB/CIFS and S3 repository managers to the shared whole-disk restore engine.
- [x] Support age symmetric decryption with one-shot Cockpit passphrase handoff on the Live client.
- [x] Support symmetric age passphrase encryption for whole-disk capture through Cockpit; partition and logical-volume capture remain recipient-based.
- [x] Implement exact whole-disk target resolution, pre-write revalidation and
      execution through the existing verified whole-disk restore engine.
- [ ] Execute the automated repository-manager integration tests and add Live acceptance coverage for private credentials, provider mount failures and interrupted restore cleanup.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Run the automated tests and add coverage for tampered answers, repository errors, ambiguous targets, target swaps and interrupted restore. BIOS/UEFI boot, Caddy against real networks and physical restore are optional operator acceptance, not software completion gates.

Each Live PXE restore writes start, progress and terminal events to
`/var/lib/feclora/pxe/operations.jsonl`. Cockpit's local Operation history
merges this journal with durable local operations and marks stale in-progress
entries interrupted after the originating process exits. PXE history entries
are read-only in Cockpit; the identity-free Client does not send authenticated
results to the Server.

The managed repository-manager whole-disk software path and age passphrase handoff are connected. Automated software tests are the release gate; BIOS/UEFI PXE boot and physical restore remain optional operator acceptance.
