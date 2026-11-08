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
- [x] Durable deployment journals and explicit interrupted-job reconciliation.
- [x] Cockpit React/PatternFly package and privileged allowlisted backend.
- [x] Cockpit local operations wizard: disk/partition capture, restore and clone.
- [x] Cockpit storage/image inventory, operation journal summary and local image-security setup.
- [x] Cockpit Terminal remains available for system administration.

## Remaining implementation work

### Cockpit remote deployment

- [ ] Server setup wizard: select and validate network interface, ProxyDHCP vs isolated DHCP, address pools, PXE services and firewall scope.
- [ ] Managed deployment CA and Server identity administration from Cockpit.
- [ ] Client CSR import/approval, certificate issue/rotation/revocation and age-recipient management from Cockpit.
- [ ] Client enrollment workflow and local target approval from Cockpit.
- [ ] Deployment job wizard: signed image, operation, enrolled clients, unicast/multicast transport, multicast group/port and start policy.
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
- [ ] Publish the design and operations documentation through GitHub Pages.

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
