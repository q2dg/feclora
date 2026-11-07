# feclora: Clonezilla Live and Server Edition functional parity

## Product goal

feclora is a Fedora-based project with two operating modes:

1. **Live/rescue mode**: boot one machine from USB/DVD/PXE to save, restore, or clone its disks.
2. **Server mode**: centrally orchestrate unattended imaging and deployment to many PXE-booted clients, including unicast and multicast/broadcast delivery.

Clonezilla Live and Clonezilla Server Edition (SE) define the user-visible feature target. Clonezilla Lite Server deployment workflows are also relevant. Clonezilla is a functional benchmark only: feclora must not depend on Clonezilla, DRBL, or any ocs-* program or script.

## Live/rescue feature map

| User-visible capability | Generic implementation primitives | Status |
|---|---|---|
| Discover disks, partitions and filesystems | lsblk, blkid, findmnt, udev | Inventory exists; safety checks incomplete |
| Save/restore whole-disk images | partclone.*, dd, sfdisk, sgdisk | Not implemented |
| Save/restore individual partitions | partclone.*, dd | Not implemented |
| Direct disk-to-disk cloning | Partition-table tools + Partclone per partition; raw-copy fallback | Not implemented |
| Filesystem-aware used-block imaging | Partclone filesystem-specific programs | Discovery only |
| Raw imaging for unsupported filesystems | dd | Not implemented |
| Compression and integrity verification | gzip, pigz, zstd, xz, sha256sum | Discovery only |
| GPT/MBR partition-table handling | sfdisk, sgdisk, parted | Discovery only |
| LVM and encrypted volumes | lvm2, cryptsetup | Packages/discovery; workflows not implemented |
| Remote image repositories | SSH/SFTP, NFS, SMB/CIFS, WebDAV | Not implemented |
| Bootloader/boot-area preservation | dd, partition-table and bootloader utilities | Not implemented |
| Interactive rescue UI | dialog initially | Read-only device browser exists |

## Server-mode feature map

| User-visible capability | Generic implementation primitives | Status |
|---|---|---|
| Central image repository | Local filesystem; NFS, SMB/CIFS, SSH/SFTP, WebDAV | Not implemented |
| Central deployment job management | feclora server-side job/configuration service | Not implemented |
| Client network boot | DHCP or existing DHCP integration, TFTP, PXE/iPXE, HTTP boot where firmware supports it | Not implemented |
| UEFI and legacy BIOS client boot | GRUB/iPXE/Syslinux-compatible boot chain and tested firmware assets | Not implemented |
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
| Safe network isolation | Dedicated VLAN/subnet or isolated deployment network; explicit DHCP ownership/relay | Not implemented |
| Reboot/poweroff after deployment | Client-side systemd/runtime action under job policy | Not implemented |

## Server architecture boundary

The server edition is not merely a multicast command wrapped in a menu. It requires a coordinated server and client system:

- **Server control plane**: creates jobs, selects image and operation, defines eligible clients, start conditions, concurrency and completion policy.
- **Boot services**: provisions or integrates with DHCP, TFTP and PXE/iPXE/HTTP boot. It must detect and avoid competing with an existing DHCP server unless the administrator explicitly configures a supported relay/proxy arrangement.
- **Image/data plane**: exposes repositories and streams data by unicast or multicast/broadcast. Multicast group selection, interface selection and network capacity must be explicit.
- **Client runtime**: boots independently of the installed OS, authenticates the deployment job, discovers local storage, validates the target and performs the operation using generic utilities.
- **Observability**: records client identity, selected disk, image, progress, exit status and errors for each deployment.

A deployment must never start merely because a machine PXE-boots onto the network. The server must restrict eligible clients and require an explicitly armed job. The client must verify its identity and target disk according to the job policy before destructive writes.

## Generic-tools-only rules

1. Do not invoke, package, port, or depend on ocs-sr, ocs-onthefly, ocs-live, any other ocs-* script, or DRBL.
2. Prefer independently maintained tools already packaged for Fedora.
3. Use Partclone for supported filesystems and raw copying when necessary; do not invent a filesystem imaging engine.
4. Use standard partitioning, compression, checksum, encryption, filesystem, network boot and transport tools rather than reimplementing them.
5. feclora code is limited to UI, control-plane/job orchestration, client coordination, safety validation, progress, logs, metadata and integration.
6. Feature parity means equivalent user-visible workflows, not compatibility with Clonezilla's private image layout, command syntax, or internal scripts.
7. Server-mode network services must be opt-in, bound to explicitly selected interfaces, and accompanied by clear warnings about DHCP/PXE scope and network isolation.

## Delivery strategy

1. Complete and test single-machine inventory, save, restore and disk-to-disk clone workflows first.
2. Define a stable image manifest and a client job protocol.
3. Implement a one-client PXE/iPXE boot and unattended restore path.
4. Add server job management, client identity/allowlisting and result reporting.
5. Add unicast deployment to multiple clients.
6. Add multicast/broadcast transport using a generic transport such as UDPcast, with client-count/deadline start conditions and recovery/error reporting.
7. Add Wake-on-LAN, capacity controls, network isolation guidance and a repeatable multi-client test lab.

## Acceptance

A capability is complete only when it works in the generated Fedora ISO/server environment with generic tools, safe defaults, progress/error reporting, and repeatable tests. Server acceptance requires multiple disposable PXE clients on an isolated test network; a successful single-client test is not evidence that multicast or mass deployment works.