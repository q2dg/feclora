# Unattended restore from ISO or PXE

## One Live system, one restore path

Feclora ISO and PXE boot the same Fedora Live image. The Feclora PXE
Server is a single deployment component that includes DHCP, Caddy and the
services needed to publish Live boot assets and unattended answer files.
DHCP and Caddy are not external infrastructure in this architecture.

The PXE Server serves the Live kernel, initramfs and squashfs and publishes
the JSON answer file through Caddy. It does not mount repositories, proxy
image data or execute restoration. The Live Client retains its local operation
journal and may send best-effort operational telemetry to the Server; those
reports are not authenticated proof of a restore result.

The canonical remote deployment definition is a schema-v1 DeploymentJob
JSON document. Interactive ISO/Live jobs and unattended shared-answer jobs
use this same contract. The schema keeps boot method and
data transport as separate concepts: `boot_method` describes how the Live
system started, while `transport` describes how image data is delivered.
The shared schema-v1 answer path submits each Client to the same persistent
authenticated DeploymentJob runtime, regardless of whether Live started from
USB/ISO or PXE. It supports whole-disk image restore over unicast or multicast;
for multicast, all authorized Clients must reach READY before the Server
automatically starts the single UDPcast image transmission. PXE is only an
optional way to boot Live and locate the same shared answer file.

- ISO/Live: the operator selects the Server network interface and configures
  each Client's network before joining a deployment.
- PXE: DHCP configures the Client network during boot, represented by
  network_interface: "auto". The iPXE handoff supplies the job-specific HTTP
  answer URL and the Client MAC used for authorization and stable target
  lookup.

For compatibility, the older schema-v2 unattended answer remains accepted
by the Live answer downloader. New unattended jobs use the shared DeploymentJob
schema, `start_policy: "automatic"`, explicit destructive confirmation, an
authorized client list and a stable WWN/serial target binding for every client.
The same JSON is downloaded by all clients; each client selects its own entry
from `target_bindings`. The boot method does not select the data transport or
a separate answer-file format. The ISO/Client deployment form can
import that same JSON from a local file, HTTP(S), a configured mounted
filesystem repository, S3, or SCP using a saved SSH key and pinned known_hosts.
Remote documents are downloaded with a 64 KiB bound and validated on the
Server before their fields are populated in the form; the operator must review
the resulting job before creating it.

After the data has been staged and verified, the TLS unicast Client runtime,
the multicast receiver and the PXE Live adapter all call the same
manifest-backed restore dispatcher at
src/feclora/deployment/restore_execution.py. Boot admission, target selection
and transfer remain mode-specific; the disk/partition/logical-volume restore
engines and their post-write verification are shared.

The legacy ISO option-224 locator remains available for existing deployments.
The PXE iPXE handoff passes its job-scoped answer URL directly to the Live
service. If no unattended answer is supplied, the Live system remains in the
normal interactive Feclora session.

## Caddy answer URL

The job-scoped publication remains:

http://<caddy-ipv4>:<port>/answers/<job-uuid>/answer.json

For ISO clients, DHCP option 224 carries the stable locator:

http://<caddy-ipv4>:<port>/unattended-answer.json

When an answer is published, the Server atomically updates this stable Caddy
path to reference the most recently published job answer. Revoking that job
or starting a new PXE session removes the current alias. This lets the
operator change the current answer without changing the ISO or its boot
configuration. The URL is a public locator, not a client credential. It is a
shared deployment setting: every ISO client receiving option 224 sees the
same currently published answer, not a per-client assignment.

In authoritative/isolated DHCP mode, Feclora dnsmasq sends option 224 to
ordinary DHCP clients. In ProxyDHCP mode, dnsmasq can send it only in the
PXE-specific proxy response; a locally booted ISO receives its lease from
the upstream authoritative DHCP server, which must also be configured to
send option 224 if ISO unattended discovery is required in that network.
The PXE Server still owns its DHCP/ProxyDHCP component; this distinction is
a consequence of ProxyDHCP not assigning the client's IP lease.

The downloader rejects redirects, bounds the response to 64 KiB, and
validates the JSON before starting any storage operation. The answer endpoint
must be reachable from the Live environment over the configured network.

## Answer contents and destructive authorization

The answer is declarative JSON. It describes a restore operation, image ID,
managed repository ID, stable target identity (WWN and/or serial), and explicit
destructive-start flags. It must not contain shell commands, arbitrary
executable arguments, device paths, passwords, private keys, bearer tokens or
per-client identity material.

The target is resolved against the current block-device inventory. Exactly
one whole disk must match, and its stable identity is checked again immediately
before the first write. Ambiguous or missing targets fail closed. Image
artifacts are checked against manifest size and SHA-256 metadata and the
restore engine performs its configured post-write verification.

For unattended multicast, the Server publishes **one answer document for the
entire client group**. Every Client downloads that same JSON. Its MAC address
selects one entry in the shared `target_bindings` map; it does not receive a
customized answer. All selected Clients independently validate their own
destination and report READY over the existing authenticated control channel.
The Server starts one UDPcast image transmission only after every authorized
Client is READY. Each Client stages and verifies the artifacts before its local
restore dispatcher writes to the bound disk.

Because the answer authorizes destructive writes, only publish it after
reviewing the target and image. The current answer transport is plain HTTP:
the deployment explicitly trusts its configured Caddy network and does not
provide cryptographic authentication or TLS for this endpoint. Do not
expose the answer endpoint to untrusted networks.

## Repository access

After boot, the Live client accesses image storage directly. The PXE Server is
not a repository proxy. ISO and PXE must use the same Feclora repository
configuration and protected credential handling; no repository secrets are
placed in the answer file.

The answer contains only a repository ID. The Live client resolves it
through Feclora's existing RemoteRepositoryManager for SSHFS, NFS and SMB/CIFS,
including mount verification, usage leases and protected credentials. S3 is
resolved through S3RepositoryManager and its encrypted credential store; image
sets are staged locally through the existing object repository adapter. The
PXE Server does not connect to, proxy or receive data from these repositories.

## Current implementation status

- [x] PXE boots the same Fedora Live kernel, initramfs and squashfs as the ISO.
- [x] ISO/USB DHCP discovery and optional PXE iPXE handoff download the same bounded, validated Caddy answer.
- [x] ISO and PXE share the same Live answer-fetch service and parser;
      ISO discovers the stable current-answer URL through DHCP option 224.
- [x] Whole-disk restore resolves WWN/serial, rechecks the target before writing
      and uses Feclora's verified disk restore engine.
- [x] Keep the ISO generic and discover the current answer URL from DHCP;
      no Caddy address is embedded in the ISO.
- [ ] Validate option 224 delivery on physical clients in authoritative DHCP
      mode and document upstream DHCP configuration for ProxyDHCP networks.
- [x] Resolve answer repository IDs through the normal SSHFS, NFS, SMB/CIFS
      and S3 repository managers, without adding a second credential system.
- [x] Use one schema-v1 DeploymentJob contract for interactive and unattended jobs, independent of ISO/USB or PXE boot.
- [x] Route unattended shared-answer unicast/multicast and interactive authenticated
      restores through the shared manifest-backed restore dispatcher.
- [x] Preserve legacy schema-v2 PXE answer compatibility during migration.
- [ ] Run physical ISO/PXE acceptance with DHCP, repository credentials,
      target ambiguity/swap, interruption and post-write verification.

Automated Python tests and frontend build run in GitHub Actions. These tests do
not replace acceptance on real PXE firmware, physical NICs, repositories and
block devices; no physical-device deployment has been claimed as tested.
