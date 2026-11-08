# feclora: Clonezilla Live and Server Edition functional parity

## Product goal

feclora is one Fedora-based bootable ISO with a startup menu for selecting the operating mode:

1. **Local rescue (Live)**: save, restore, and clone disks on the machine booted from the ISO.
2. **Server**: coordinate unattended imaging and deployment to multiple PXE-booted clients.
3. **Client**: join an authorized network deployment session and execute its assigned imaging task.

This is one ISO and one shared runtime/toolset, not separate Live and Server images. Server and client functions are selected from the startup menu. Network services remain stopped unless the operator explicitly selects Server mode.

Clonezilla Live and Clonezilla Server Edition define the user-visible feature target. Clonezilla Lite Server deployment workflows are also relevant. Clonezilla is a functional benchmark only: feclora must not depend on Clonezilla, DRBL, or any ocs-* program or script.

## Live/rescue feature map

| User-visible capability | Generic implementation primitives | Status |
|---|---|---|
| Discover disks, partitions and filesystems | lsblk, blkid, findmnt, udev | Inventory exists; safety checks incomplete |
| Save/restore whole-disk images | partclone.*, dd, sfdisk, sgdisk | Implemented in code and Local rescue UI; mocked tests only, runtime validation pending |
| Save/restore individual partitions | partclone.*, dd | Implemented in code and Local rescue UI; mocked tests only, runtime validation pending |
| Direct disk-to-disk cloning on one machine | dd direct block copy with source/target safety and exact byte limit | Implemented in code and Local rescue UI; mocked tests only, runtime validation pending |
| Direct disk-to-disk cloning between two machines | Authenticated client/server stream over TLS; generic raw or Partclone data plane | Planned; not implemented |
| Filesystem-aware used-block imaging | Partclone filesystem-specific programs | Discovery only |
| Raw imaging for unsupported filesystems | dd | Not implemented |
| Compression and integrity verification | gzip, pigz, zstd, xz, sha256sum | Discovery only |
| GPT/MBR partition-table handling | sfdisk, sgdisk, parted | Discovery only |
| LVM logical volumes and encrypted volumes | lsblk, pvs, vgs, lvs, lvm2, cryptsetup, dmsetup | Read-only PV/VG/LV topology is included in inventory; activation, snapshots, LUKS integration and volume-aware capture/restore remain pending |
| Stratis pools and filesystems | /dev/stratis, sysfs device-mapper topology, stratis-cli, stratisd | Active pool/filesystem links and backing block-device chains are inventoried read-only; stopped pools, authoritative daemon metadata and management workflows remain pending |
| Btrfs filesystems | lsblk, btrfs-progs, Partclone where supported | Filesystem classification and read-only multi-device membership scan are included; partition capture verifies single-device scope and rejects multi-device Btrfs; subvolume/snapshot-aware imaging and restore remain pending |
| Remote image repositories | SSH/SFTP, NFS, SMB/CIFS, WebDAV | Not implemented |
| Bootloader/boot-area preservation | dd, partition-table and bootloader utilities | Not implemented |
| Interactive rescue UI | dialog initially | Capture, restore and direct local disk clone actions connected; progress/cancellation and runtime validation pending |

## Server-mode feature map

| User-visible capability | Generic implementation primitives | Status |
|---|---|---|
| Central image repository | Local filesystem; NFS, SMB/CIFS, SSH/SFTP, WebDAV | Not implemented |
| Central deployment job management | feclora server-side job/configuration service | Not implemented |
| Client network boot | dnsmasq ProxyDHCP/isolated DHCP, TFTP, iPXE, Caddy HTTP Live boot | Server UI, config validation, boot-tree staging and transient service lifecycle are implemented; real daemon, BIOS/UEFI and client boot validation pending |
| UEFI and legacy BIOS client boot | Fedora RPM-owned iPXE BIOS and UEFI firmware assets, HTTP iPXE script | Firmware staging and chainloading configuration are implemented; Secure Boot compatibility and hardware validation pending |
| Client discovery and identity | DHCP leases, MAC inventory/reservations, client allowlists | Not implemented |
| Unattended client imaging | feclora client runtime + generic storage tools | Not implemented |
| One-to-many unicast deployment | Standard IP networking and per-client sessions | Not implemented |
| Broadcast deployment | UDP broadcast transport where network topology permits | Not implemented |
| Multicast deployment | udpcast sender/receiver or another independent multicast transport | Not implemented |
| Deployment start policy | Expected client count, arrival deadline, manual start, explicit allowlist | Not implemented |
| Wake clients remotely | Wake-on-LAN (wakeonlan/etherwake) | Not implemented |
| Progress and per-client results | Server job state, client status channel, structured logs | Not implemented |
| Concurrency and resource limits | Server-side scheduler, network/storage capacity controls | Not implemented |
| Secure client authorization | Per-job tokens/keys, allowlisted identities, authenticated control channel | Not implemented |
| Safe network isolation | Interface-bound dnsmasq, ProxyDHCP/authoritative DHCP profiles, interface-zone firewalld rules | Interface/address revalidation, explicit isolated-DHCP typed confirmation and current NetworkManager lease warning implemented; physical VLAN/isolation validation pending |
| Reboot/poweroff after deployment | Client-side systemd/runtime action under job policy | Not implemented |

## Single-ISO mode architecture

The startup menu is the entry point for all operating modes. It must be present
in the same booted ISO and dispatch to separate application modules/processes:

- **Local rescue** opens the local imaging UI.
- **Server** starts the server control plane and, only after explicit operator
  configuration/confirmation, the required network boot and deployment services.
- **Client** starts the PXE/deployment client runtime and joins an authorized job.

The mode selector itself must not start DHCP, TFTP, HTTP, multicast, or other
network services. Selecting Server is an explicit action, and the operator
must choose the network interface and DHCP integration/scope. The system must
detect likely competing DHCP services and fail safely rather than silently
starting another one.

The server and client modes share the same ISO, kernel, initramfs, storage
utilities, image manifest format, safety validation and logging facilities.
Role-specific services are activated on demand and stopped when leaving that
mode or shutting down.

A deployment must never start merely because a machine PXE-boots onto the
network. The server must restrict eligible clients and require an explicitly
armed job. The client must verify its identity and target disk according to
the job policy before destructive writes.

## Generic-tools-only rules

1. Do not invoke, package, port, or depend on ocs-sr, ocs-onthefly, ocs-live, any other ocs-* script, or DRBL.
2. Prefer independently maintained tools already packaged for Fedora.
3. Use Partclone for supported filesystems and raw copying when necessary; do not invent a filesystem imaging engine.
4. Use standard partitioning, compression, checksum, encryption, filesystem, network boot and transport tools rather than reimplementing them.
5. feclora code is limited to UI, control-plane/job orchestration, client coordination, safety validation, progress, logs, metadata and integration.
6. Feature parity means equivalent user-visible workflows, not compatibility with Clonezilla's private image layout, command syntax, or internal scripts.
7. Network services must be opt-in, bound to explicitly selected interfaces, and accompanied by clear warnings about DHCP/PXE scope and network isolation.

## Delivery strategy

1. Complete and validate single-machine inventory, save, restore and direct disk-to-disk cloning.
2. Define a stable image manifest and an authenticated, integrity-protected client/server protocol.
3. Implement one-to-one remote disk cloning: the source host streams to an explicitly authorized receiver host, with independent source/target safety checks and end-to-end verification.
4. Implement the Client mode and a one-client PXE/iPXE boot and unattended restore path.
5. Implement Server mode job management, client identity/allowlisting and result reporting.
6. Add unicast deployment to multiple clients.
7. Add multicast/broadcast transport using a generic transport such as UDPcast, with client-count/deadline start conditions and recovery/error reporting.
8. Add Wake-on-LAN, capacity controls, network isolation guidance and a repeatable multi-client test lab.

## Acceptance

A capability is complete only when it works in the same generated Fedora ISO with generic tools, safe defaults, progress/error reporting, and repeatable tests. Server acceptance requires multiple disposable PXE clients on an isolated test network; a successful single-client test is not evidence that multicast or mass deployment works.
