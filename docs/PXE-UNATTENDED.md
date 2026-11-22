---
layout: default
title: PXE Live and unattended answer files
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

![Illustrative PXE boot workflow]({{ '/assets/mockups/pxe-workflow.svg' | relative_url }})

*Illustrative mockup — not a screenshot. Interactive Live boot and unattended answer execution are separate paths.*


# PXE Live and unattended answer files

## Intended operating model

For the common ISO/PXE answer-file contract and dynamic URL discovery, see
[UNATTENDED-RESTORE.md](UNATTENDED-RESTORE.md).

PXE is a network boot method for the **same Feclora Fedora Live environment**
used by the ISO. It is not a separate thin client, installer, or per-machine
provisioning workflow. The default `boot.ipxe` starts that Live environment
directly in interactive mode; it does not display a menu or launch a restore.
The answer-file handoff described below is a separate, explicitly configured
unattended path.

## Shared unattended answer for ISO and PXE Live

Unattended execution is independent of the boot method. The same schema-v1 DeploymentJob JSON can be consumed by a generic ISO/USB Live boot or by a PXE boot. `boot_method` describes how Live started; `transport` independently selects unicast or multicast image delivery. For multicast restore, every authorized Client reads the identical answer JSON and joins the same authenticated Server job. Each Client uses its local MAC only to select its own target binding from that shared document.

- `boot_method: iso` is the default for USB/ISO Live; `boot_method: pxe` is used only when iPXE starts Live directly.
- `network_interface` names the Server interface for ISO/USB workflows; PXE uses `auto` because DHCP already configured Live networking.
- `start_policy: automatic` and `confirm_destructive: true` explicitly opt in to unattended execution. This policy is not reserved for PXE.
- authorized_clients lists the expected client MAC addresses. MAC addresses are operational selectors, not authentication credentials.
- target_bindings maps every client MAC to a stable disk WWN and/or serial number. The client checks that binding before restore and revalidates the disk identity immediately before writing.
- repository_id references a repository already configured on the Live client; credentials are never embedded in the JSON.

The Live answer downloader submits schema-v1 jobs to the persistent authenticated Client runtime rather than restoring directly. For multicast, each Live Client independently resolves its local interface route to the shared multicast group, validates its own MAC-to-WWN/serial target binding, stages and verifies the same image artifacts, then invokes the shared manifest-backed restore dispatcher at `src/feclora/deployment/restore_execution.py`. The Server starts the single multicast transmission automatically only after every authorized Client is READY. Once the cohort is armed, a Client that fails START or loses its control session while receiving the offer is marked failed independently; it does not cancel peers that accepted the offer. The same manifest and artifact stream are sent once to the remaining receivers, and UDPcast requires at least one receiver rather than the original cohort size. A sender/repository-wide error still fails the active receivers because they share the same unavailable source stream. Terminal results and progress are collected concurrently per Client, so a stalled or disconnected control session does not delay recording the other Clients' outcomes. PXE is only an optional Live boot transport; answer discovery also works from ISO/USB through DHCP option 224. The Server sends image data directly to multicast receivers.

The Textual PXE panel can generate this JSON, let the operator review and save it, or import a JSON document from local upload, HTTP(S), a configured remote repository, or SCP. The ISO/Client deployment panel can import the same schema-v1 document from a local file, HTTP(S), a mounted and verified repository, S3, or SCP through saved SSH credentials. Both import paths validate the document with `DeploymentJob.from_dict()` before the operator reviews and creates or publishes the job. The legacy schema-v2 PXE answer remains readable for compatibility and retains its original local unicast restore path. New schema-v1 PXE jobs use the shared authenticated deployment control plane and support whole-disk unicast or multicast restore. All clients fetch the same published JSON; `target_bindings` is a shared MAC-to-stable-disk map, not a set of per-client answer files.

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
shared answer JSON through Caddy. It does not proxy storage access, mount remote
repositories or execute restoration. Admitted Live clients can send bounded
start, progress and terminal restore events back to the Server over the same
plain-HTTP service. Both ISO and PXE enter the same Live answer-fetch service,
validator and restore client. The Live service checks the NetworkManager
DHCPv4 lease for option 224 on ISO boots and otherwise leaves interactive
boots unchanged.

No per-Client identity medium or credential provisioning is required. The
PXE admission ledger records reported MAC addresses for operational selection
and limits only.

## Deployment preparation

The Textual Server setup accepts a prewritten JSON answer from three
sources: a local file upload, an HTTP/HTTPS URL, or a path inside an already
configured image repository. For HTTP/HTTPS, the Server downloads the document
directly, verifies TLS certificates, rejects redirects and embedded URL
credentials, and enforces the 64 KiB limit. For SSHFS/SFTP, NFS and SMB/CIFS,
the selected repository must already be mounted and identity-verified; the
answer path is relative to its mount root. For S3, the path is an object key
relative to the configured bucket prefix. SCP can also fetch directly from a
configured SSHFS repository definition, reusing its protected SSH private key
and known_hosts data with strict host-key verification; the SSHFS mount need
not be active for this SCP mode. Repository credentials are never entered
into the answer form.

All sources pass the same strict JSON schema validation before the Server
publishes the document through Caddy over HTTP under a generated job UUID. It
also publishes an iPXE admission wrapper and a separate job-specific boot
script. The boot script is available only through the admission endpoint, not
through Caddy's static file server.

The PXE Server does not host, copy, mount or proxy the image repository. It
serves the Live boot assets and the answer JSON only. The Live client is
responsible for connecting directly to external SSHFS, NFS, SMB/CIFS and S3
repositories using Feclora's normal client-side repository configuration and
protected credential handling. Do not send repository credentials in the
answer file. PXE job participation is associated with the reported MAC address.

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

## Security boundary

An answer file can authorize a destructive operation, so it must not be
treated as harmless configuration. It is published only after administrator
action through Textual, is scoped to one generated job UUID, and can currently
be revoked explicitly from the same Textual form. A new PXE session clears
stale published answer directories. Successful explicit deployment-job
cancellation revokes its answer. Answers do not expire automatically and can
be reused until revoked or cleared by a new PXE session. Clients validate the
schema and repository integrity metadata before any write. For this deployment, the operator explicitly chooses to trust the answer
served by the configured HTTP server. This is an operational trust assumption,
not cryptographic authenticity: an attacker able to modify HTTP traffic or the
server's published file can alter the instructions. The answer is served over HTTP without cryptographic authenticity or transport-confidentiality protection. The workflow does not identify individual Clients; its admission ledger records reported MAC addresses for operational limits only. Optional age encryption protects image artifacts,
not the answer JSON or HTTP transport.

The PXE Server can register the MAC address supplied by iPXE on the first
unattended boot request. In Textual, the administrator may configure a maximum
number of distinct MAC addresses, a serving-time deadline, or both. Both fields
are empty by default: no client-count or time limit is imposed unless the
administrator explicitly enters one. Repeated requests from a MAC already
registered do not consume another client slot. When a configured client cap
is reached, new MAC addresses are refused; after a configured time deadline,
all admission and boot-script requests are refused. The ledger is root-owned
and persists for the lifetime of the PXE session. This is an operational
admission limit, not a security boundary: a Client can spoof a MAC address. The admission gate does
not stop an already-running restore, invalidate a boot script already
retrieved by a client, or revoke the JSON answer file itself. The JSON answer
URL remains a public job-scoped locator until explicit revocation or stale
session cleanup; the MAC limit is an operational admission control, not a
security boundary.

## Repository and client model

ISO and PXE Live clients run the same Feclora application and access
repositories directly, using the normal client-side repository manager and
its protected credential storage. The PXE Server is not a storage gateway.
Clients are selected operationally by the reported MAC address; no per-Client
credentials are part of this workflow. The answer file contains repository selection
and restore parameters only, never passwords, keys or credential-bearing URLs.
The unattended PXE adapter resolves the selected ID through the existing
client-side repository managers. SSHFS, NFS and SMB/CIFS use the normal managed
mount lifecycle and protected credentials; S3 uses the normal encrypted
credential store and object repository adapter. The PXE answer never contains
a URL, credential reference or secret.

PXE is only a boot transport. After Live starts, storage access and
restoration are performed by the Client itself. The Client sends best-effort
start, progress and terminal events to the Server's /pxe/report/<job-uuid>
endpoint. The Server stores these in the private
/var/lib/feclora/pxe/remote-reports.jsonl journal and includes them in
Textual's Operation history. A failed or unavailable report transport never
interrupts the disk restore. The Client also retains its local operation
journal.

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
- [x] Publish one shared schema-v1 DeploymentJob answer for every selected
      Client; each Client selects only its own target from the common
      `target_bindings` map. No per-Client answer files are generated.
- [x] Route schema-v1 PXE clients through the authenticated persistent Client
      runtime and create/start the matching Server job from the published
      answer. Automatic multicast waits for every authorized Client to reach
      READY before the Server sends the image once.
- [x] Advertise the stable current-answer URL as DHCP option 224 in
      authoritative DHCP mode and the PXE-specific proxy response; discover it
      from the Live NetworkManager lease on ISO boots.
- [x] Resolve the repository ID using the normal managed repository managers, unique WWN/serial target resolution,
      pre-write identity revalidation and existing whole-disk restore engine.
- [x] Add one Textual JSON answer-file upload control; the repository ID is
      taken directly from the JSON document.
- [x] Validate and atomically publish/revoke job-scoped JSON files through Caddy.
- [x] Register unique iPXE MAC addresses in a persistent Server-side admission ledger; enforce configurable distinct-client and/or elapsed-time limits, and deny direct static access to the boot script.
- [x] Clear stale answer files and handoff scripts when a new PXE session starts.
- [x] Keep answer files reusable; explicit revocation and stale-session cleanup remain available. Successful deployment-job cancellation revokes its published answer.
- [x] Connect the normal SSHFS, NFS, SMB/CIFS and S3 repository managers to the shared whole-disk restore engine.
- [x] Support age symmetric decryption with one-shot Textual passphrase handoff on the Live client.
- [x] Support symmetric age passphrase encryption for whole-disk capture through Textual; partition and logical-volume capture remain recipient-based.
- [x] Implement exact whole-disk target resolution, pre-write revalidation and
      execution through the existing verified whole-disk restore engine.
- [ ] Execute the automated repository-manager integration tests and add Live acceptance coverage for private credentials, provider mount failures and interrupted restore cleanup.
- [x] Use the operator-selected HTTP trust assumption; no cryptographic integrity mechanism is provided.
- [ ] Run the automated tests and add coverage for tampered answers, repository errors, ambiguous targets, target swaps and interrupted restore. BIOS/UEFI boot, Caddy on real networks and physical restore are mandatory maintainer-run release acceptance, separate from software completion gates.

Each Live PXE restore writes start, progress and terminal events to
`/var/lib/feclora/pxe/operations.jsonl` and sends best-effort copies to the
Server. Textual's Operation history shows Server-received remote Client
events alongside local operations. Remote records include the job UUID and
reported MAC address. Because the transport is plain HTTP and the MAC is
client-reported, these records are operational telemetry, not authenticated
proof of which machine performed a restore or whether a reported result is
true. The Server validates event schemas, bounds payload sizes, rejects
reports from MACs not admitted for the current session, and ignores duplicate
event IDs.

The managed repository-manager whole-disk software path and age passphrase handoff are connected. Automated tests gate software correctness, but they do not establish real PXE boot or restore behavior. BIOS/UEFI PXE boot, DHCP behavior, repository access and destructive restore on disposable targets remain mandatory maintainer-run release acceptance; record them in [MAINTAINER-ACCEPTANCE.md](MAINTAINER-ACCEPTANCE.md).
