# Unattended restore from ISO or PXE

## One Live system, one restore path

Feclora ISO and PXE boot the same Fedora Live image. The Feclora PXE
Server is a single deployment component that includes DHCP, Caddy and the
services needed to publish Live boot assets and unattended answer files.
DHCP and Caddy are not external infrastructure in this architecture.

The PXE Server serves the Live kernel, initramfs and squashfs and publishes
the JSON answer file through Caddy. It does not mount repositories, proxy
image data, execute restoration, or receive client operation results.

Both boot methods use the same answer schema, downloader, validator and Live
restore client. The current answer URL is supplied dynamically:

- ISO: NetworkManager reads DHCP private option 224 from its active IPv4
  lease. The ISO contains no Caddy address and needs no rebuild when the
  server address or port changes.
- PXE: the iPXE handoff passes the job-scoped answer URL directly to the same
  Live service. The PXE DHCP proxy also advertises option 224 in its
  PXE-specific response.

The Live service runs after network-online on both ISO and PXE boots. It
prefers an explicit PXE/kernel handoff; otherwise it looks for option 224.
If no answer URL is supplied, it exits without changing the normal
interactive Feclora session.

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

Because the answer authorizes destructive writes, only publish it after
reviewing the target and image. The current answer transport is plain HTTP:
the deployment explicitly trusts its configured Caddy network and does not
provide cryptographic answer signatures or TLS for this endpoint. Do not
expose the answer endpoint to untrusted networks.

## Repository access

After boot, the Live client accesses image storage directly. The PXE Server is
not a repository proxy. ISO and PXE must use the same Feclora repository
configuration and protected credential handling; no repository secrets are
placed in the answer file and no client authentication/enrollment is added.

The answer contains only a repository ID. The Live client resolves it
through Feclora's existing RemoteRepositoryManager for SSHFS, NFS and SMB/CIFS,
including mount verification, usage leases and protected credentials. S3 is
resolved through S3RepositoryManager and its encrypted credential store; image
sets are staged locally through the existing object repository adapter. The
PXE Server does not connect to, proxy or receive data from these repositories.

## Current implementation status

- [x] PXE boots the same Fedora Live kernel, initramfs and squashfs as the ISO.
- [x] PXE unattended handoff downloads a bounded, validated Caddy answer.
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
- [ ] Unify answer-driven execution with durable local operation history and
      the normal unattended restore-profile safety/replay policy.
- [ ] Run the automated test suite and add Live acceptance coverage for ISO/PXE
      handoff, private repository credentials, target ambiguity/swap, interruption
      and post-write verification.

No test suite or ISO build has been run as part of these source changes.
