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
- [ ] Full managed deployment CA lifecycle and Server identity rotation/renewal from Cockpit (initial identity bootstrap and Client enrollment are implemented).
- [ ] Client certificate renewal/revocation and age-recipient management from Cockpit.
- [x] Client enrollment preparation and completion from Cockpit, including local key generation and removable-media exchange.
- [ ] Local destructive-target approval for remote jobs from Cockpit.
- [x] Cockpit remote-job definition wizard: validate enrolled Clients, image/signature, interface and transport, then persist a hash-chained job journal (definition only; no start).
- [x] Cockpit audit-only reconciliation of interrupted job journals, requiring inspection and exact typed confirmation; no storage operation is resumed.
- [ ] Persistent job execution service and lifecycle controls.
- [ ] Persistent job daemon/service lifecycle so a browser disconnect does not terminate the control plane.
- [ ] Arm, cancel, inspect and reconcile jobs through Cockpit.
- [ ] Per-client state, byte progress, throughput, results and error logs.
- [ ] Multicast network preflight reporting, including staging capacity and operator confirmation of switch IGMP snooping/querier.
- [ ] Remote disk-to-disk clone source/receiver workflow and status in Cockpit.
- [ ] Remote repository lifecycle and secure credential management.

### Local storage workflow enhancements

- [ ] Expose partition extraction from an existing whole-disk image in Cockpit.
- [ ] Expose restore layout preview and explicit partition growth profiles where supported.
- [ ] Expand filesystem/volume-aware backup and restore for LVM, LUKS, multi-device Btrfs and Stratis; do not claim support from inventory alone.
- [ ] Add cancellable background operation lifecycle and durable progress/status after browser disconnect.
- [ ] Expose detailed operation logs and verification reports in Cockpit.
- [ ] Add remote repository selection (NFS, SMB/CIFS, SSH/SFTP) with protected credential handling.

### Project governance

- [ ] Select and document the project license and contribution policy.
- [ ] Add reproducible dependency lockfiles for the web frontend.
- [ ] Confirm GitHub Pages publication and canonical hostname. The minimalist landing page and deployment workflow are in source. GitHub Pages is enabled with GitHub Actions as the source; confirm a successful deployment run and public URL response before treating publication as complete.

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
