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
restore client. The answer URL is supplied dynamically at boot:

- ISO: the Live client obtains the current answer URL from a Feclora-specific
  DHCP option. The ISO remains generic; its boot menu does not embed a Caddy
  address and does not need rebuilding when that address changes.
- PXE: the PXE boot flow obtains the same current answer URL from the Feclora
  PXE Server and passes it to the Live environment using the PXE handoff.

The DHCP option number and its exact encoding must be defined by the Feclora
DHCP implementation; no option number is assumed by this architecture.
Both boot methods enter the same Live answer-fetch service and restore client.
With no unattended answer supplied, the normal interactive Feclora session
is unchanged.

## Caddy answer URL

The current Caddy publication format is:

http://<caddy-ipv4>:<port>/answers/<job-uuid>/answer.json

The URL is a public locator, not a client credential. DHCP supplies the
current URL to ISO clients, so changes to Caddy's address or port are handled
by updating the PXE Server's DHCP configuration rather than rebuilding the
ISO. PXE clients use the same published answer endpoint.

The downloader rejects redirects, bounds the response to 64 KiB, and
validates the JSON before starting any storage operation. The answer endpoint
must be reachable from the Live environment over the configured network.

## Answer contents and destructive authorization

The answer is declarative JSON. It describes a restore operation, image ID,
repository location, stable target identity (WWN and/or serial), and explicit
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

The current unattended answer implementation is not yet fully integrated
with Feclora's normal repository managers. Its working paths are NFS and
credential-free HTTPS. Supporting SSHFS, SMB/CIFS and private S3 in unattended
mode requires connecting the answer's repository selection to the existing
client-side managers and their protected credentials. Until then, those
providers must fail closed rather than being silently downgraded or exposing
credentials.

## Current implementation status

- [x] PXE boots the same Fedora Live kernel, initramfs and squashfs as the ISO.
- [x] PXE unattended handoff downloads a bounded, validated Caddy answer.
- [x] ISO and PXE now share the same Live answer-fetch service and parser
      contract; ISO supplies feclora.unattended_url.
- [x] Whole-disk restore resolves WWN/serial, rechecks the target before writing
      and uses Feclora's verified disk restore engine.
- [ ] Make the ISO build expose a documented boot-menu entry/configuration
      mechanism for unattended URL injection without manual kernel editing.
- [ ] Replace the PXE-specific repository adapter with the existing Feclora
      repository managers so all supported remote providers behave identically.
- [ ] Unify answer-driven execution with durable local operation history and
      the normal unattended restore-profile safety/replay policy.
- [ ] Add and run automated end-to-end tests for ISO and PXE handoff, repository
      access, target ambiguity/swap, interruption and post-write verification.

No test suite or ISO build has been run as part of these source changes.
