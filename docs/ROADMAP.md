# Roadmap

This roadmap distinguishes code implementation, Cockpit integration and
operator-owned laboratory acceptance. Feclora's primary interface is Cockpit;
the old local `dialog` menu is no longer installed in the Live package.

## Completed in source

- [x] Fedora 45 x86_64 Live-image build configuration and BIOS/UEFI boot assets.
- [x] Read-only block-device, partition and volume inventory.
- [x] Manifest-backed whole-disk and partition capture.
- [x] Verified whole-disk and partition restore engines.
- [x] Direct local disk-to-disk and partition-to-partition clone engines.
- [x] Compression, SHA-256 artifact verification, age encryption and minisign signing.
- [x] Source-safety checks, target geometry checks and explicit destructive confirmations.
- [x] Local managed CA/TLS identity bootstrap and Client CSR enrollment primitives.
- [x] Authenticated unicast deployment engine and UDPcast multicast restore engine.
- [x] PXE/iPXE boot-tree staging and transient dnsmasq/Caddy/firewalld service lifecycle.
- [x] Durable deployment journals, audit-state reconstruction from verified journals, and explicit interrupted-job reconciliation (reconstruction does not restore sessions or resume work).
- [x] Root-peer Unix IPC protocol integrated with the persistent systemd Server service and Cockpit lifecycle API.
- [x] Cockpit React/PatternFly package and privileged allowlisted backend.
- [x] Cockpit local operations wizard: disk/partition capture, restore and clone.
- [x] Cockpit storage/image inventory, operation journal summary and local image-security setup.
- [x] Cockpit Terminal remains available for system administration.
- [x] Initial Cockpit Server identity bootstrap from a currently assigned IPv4 address, including DHCP-server warning and managed trust-material initialization.
- [x] Cockpit PXE network-profile preflight and explicit activation/shutdown for ProxyDHCP and isolated DHCP, with persisted transient systemd units and reversible interface-scoped firewalld state.

## Remaining implementation work

### Cockpit remote deployment

- [x] Cockpit PXE activation/shutdown: persist transient dnsmasq/Caddy unit and interface-scoped firewalld state across API calls; stop restores the previous interface zone. Services are not enabled at boot.
- [x] Cockpit Server-side CSR inspection, explicit approval, certificate issuance, Client allowlist/age-recipient registration and public response-bundle export.
- [ ] Complete Server setup wizard: manage persistent network configuration and expose richer PXE service diagnostics.
- [x] Cockpit Server TLS certificate renewal under the existing CA, retaining the Server private key and refusing renewal while deployment services are active.
- [ ] Full managed CA lifecycle/rotation and Server identity key rotation from Cockpit; initial identity bootstrap is implemented.
- [x] Cockpit inventory of enrolled Client identities, authorized MACs and image-capture trust; exact-confirmation revocation removes future MAC authorization, signing trust and Server age-recipient mapping.
- [x] Cockpit read-only Server/Client TLS certificate expiry status with expired/30-day warning thresholds.
- [x] Complete Client certificate renewal from Cockpit through removable media: reuse and verify the existing TLS key, exact identity/MAC approval with a Server-side pinned TLS public-key continuity check, preserve age recipient and minisign trust, validate Server fingerprints and install the renewed certificate transactionally. Pre-pin legacy Clients require re-enrollment before renewal.
- [x] Cockpit Server export of the current age-recipient inventory to removable media and Client-side verification/atomic refresh, including a check that the Client's own age identity is present.
- [x] Client enrollment preparation and completion from Cockpit, including local key generation and removable-media exchange.
- [x] Read-only mTLS Client job inspection from Cockpit API without Client registration or READY transition.
- [x] Persistent non-boot-enabled Client service for unicast disk capture and disk/partition restore; READY/ARM gating, byte progress, terminal/interrupted state and no automatic reconnect/resume.
- [x] Cockpit Client multicast receive workflow: per-Client interface selection and preflight, local target approval, age-encrypted artifact staging/verification and scoped firewall lifecycle. Switch IGMP snooping/querier remains operator-verified.
- [x] Cockpit local target selection, exact typed authorization and root/mount safety preflight before Client READY for unicast jobs.
- [x] Cockpit remote-job definition wizard: validate enrolled Clients, image/signature, interface and transport, then persist a hash-chained job journal (definition only; no start).
- [x] Cockpit audit-only reconciliation of interrupted job journals, requiring inspection and exact typed confirmation; no storage operation is resumed.
- [x] Persistent single-job execution service: systemd template, mTLS listener, durable journal ownership and browser-disconnect independence (never boot-enabled).
- [x] Integrate root-only Unix IPC with the systemd service and Cockpit API; enforce peer UID, single-job ownership, exact job UUID confirmations and explicit arm/cancel semantics.
- [x] Persistent Server control-plane lifecycle survives browser disconnect; service/process restarts never resume interrupted jobs.
- [x] Start/connect, inspect live Client state, arm, pre-arm cancel, safe stop and audit reconciliation through Cockpit.
- [x] Live per-client READY/running/terminal state and service errors through Cockpit.
- [x] Per-Client disk-operation byte progress and sampled throughput over the authenticated TLS control channel; Client-local UI also tracks the image-transfer phase and byte count. Server-side transfer progress remains pending because image payloads and control frames currently share one TLS stream.
- [x] Server-side multicast restore engine, interface/route preflight, explicit arm confirmation and integrated Cockpit Server/Client receiver lifecycle.
- [x] Derive multicast staging bytes from the verified signed manifest and require each Client to pass a pre-READY free-space check with a 64 MiB safety reserve; runtime checks capacity again before receiving artifacts.
- [x] Require explicit Client and Server operator acknowledgement of switch IGMP snooping and an active querier before multicast restore is armed.
- [ ] Remote disk-to-disk clone source/receiver workflow and status in Cockpit.
- [ ] Remote repository lifecycle and secure credential management.

### Local storage workflow enhancements

- [x] Expose partition extraction from a verified whole-disk image in Cockpit, including age decrypt/re-encryption when the source is encrypted, source-signature verification and transactional publication of a newly signed partition image when a local signing key is available.
- [x] Cockpit read-only whole-disk restore layout preview with verified partition-table metadata and destination-capacity comparison; restore preserves the captured layout and leaves extra capacity unused.
- [ ] Expose explicit partition/filesystem growth profiles where supported; never resize automatically.
- [ ] Expand filesystem/volume-aware backup and restore for LVM, LUKS, multi-device Btrfs and Stratis; do not claim support from inventory alone.
- [ ] Add cancellable background operation lifecycle and durable progress/status after browser disconnect.
- [x] Expose recorded operation failure type and diagnostic text alongside the durable operation history in Cockpit.
- [x] Add on-demand structured image verification reports in Cockpit: manifest parsing, trusted minisign signature, stored SHA-256, age authentication, decompression integrity and decoded disk-size checks.
- [ ] Add remote repository selection (NFS, SMB/CIFS, SSH/SFTP) with protected credential handling.

### Project governance

- [ ] Select and publish the project software license; this requires a maintainer decision.
- [x] Document engineering, review, testing and storage-safety contribution policy in [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] Add reproducible dependency lockfiles for the web frontend.
- [ ] Verify the published GitHub Pages URL and canonical hostname from an external client. The landing page and GitHub Actions deployment are implemented; the latest Pages deployment workflow succeeded, but the public URL response has not yet been independently confirmed.

## Explicitly out of scope unless requested

- Multicast image capture.
- Concurrent unicast deployment to multiple clients.
- Wake-on-LAN.
- Automatic reboot or poweroff after imaging.
- Automatic destructive resume after interruption.
- Automatic proportional filesystem/partition growth without an explicit operator-selected layout policy.

## Operator-owned validation

The repository work does not attempt to generate the ISO or run real destructive
restoration/deployment tests on laboratory machines. The operator owns:
- building the Fedora 45 ISO from the documented build scripts;
- BIOS and UEFI boot validation;
- real disk/partition capture, restore and clone acceptance on disposable media;
- PXE client boot and network deployment acceptance;
- IGMP snooping/querier and network-capacity validation on the actual switch/VLAN.

Automated unit tests, static checks and frontend compilation remain project
responsibilities; their latest CI status must be checked before claiming they
pass.
