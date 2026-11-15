## Feclora is...

... a tool for cloning whole local disks (or partitions) in a lone computer

... a tool for cloning whole local disks (or partitions) through network nodes (in a _1 source <-> 1 destination_ "unicast" mode or in _1 source <-> N destinations_ "multicast" mode)

... a tool for creating images, which can be saved locally or in a remote SSHFS, NFS, SMB/CIFS or S3 storage server. These images are compressed, their integrity is verifiable using SHA-256 and they can be optionally encrypted using Chacha20-Poly1305 

... a tool for restoring images from a local or remote (SSHFS, NFS, SMB/CIFS os S3) storage. Notice these remote servers should be implemented by you independently. Restoration can be "unicast" ( _1 source <-> 1 destination_ ) or "multicast" (_1 source <-> N destinations_)

... a tool for running a PXE environment in order to boot network clients to be restored without having to boot them using any locally-inserted Feclora ISO. Once the client has been started, the procedure is similar to the network restoration methods mentioned previously

... a tool for run unattended restorations (whether locally or over the a network via "unicast" or "multicast", with or without PXE) through a JSON answer file

...a Live ISO running on a Fedora Server 45 (x86_64) system which automatically launches a Cockpit-based web interface inside a locked-down Firefox kiosk. The Live session is ephemeral, so credentials, certificates and temporary configuration are regenerated at boot

Feclora supports Ext4, XFS, NTFS, FAT32, exFAT and F2FS file systems, plus single-device Btrfs partitions. Unknown or unsupported content is handled as raw where safe. LVM logical volumes and raw LUKS2 containers are supported image sources under documented restrictions; Stratis is inventoried but is not a fully supported imaging target. Coordinated multi-device Btrfs imaging and snapshot-assisted capture are not supported


## Built on

Feclora brings together these projects and tools:

* [Fedora Server](https://fedoraproject.org/server/) — Operating system base
* [Cockpit](https://cockpit-project.org/) — Web-based system administration tool
* [Firefox](https://www.mozilla.org/firefox/) and [Cage](https://github.com/cage-kiosk/cage) — Locked-down graphical kiosk.
* [Partclone](https://partclone.org/) — Filesystem-aware partition imaging software
* [LVM2](https://sourceware.org/lvm2/), [Stratis](https://stratis-storage.github.io/) and [cryptsetup](https://gitlab.com/cryptsetup/cryptsetup) — Storage and encryption-layer support.
* [NetworkManager](https://networkmanager.dev/) — Network configuration daemon
* [UDPcast](https://www.udpcast.linux.lu/) — Multicast image distribution software
* [Dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html) and [iPXE](https://ipxe.org/) — Network boot and DHCP/PXE services.
* [Caddy](https://caddyserver.com/) — HTTP server used for delivery of PXE boot assets and answer files.
* [age](https://age-encryption.org/) — Optional image encryption tool.
* [zstd](https://facebook.github.io/zstd/) and [LZ4](https://lz4.github.io/lz4/) — Image compression libraries
* [Lorax](https://weldr.io/lorax/) — Live ISO construction framework.
* [QEMU/KVM](https://www.qemu.org/) — Virtualized ISO build and validation accessory tools.


## Documentation

Start with these [step-by-step "getting started" guides](https://q2dg.github.io/feclora/GETTING-STARTED.html). You can also read these other technical documents:

* [More specific operator guides](docs/GUIDES.md)
* [Feature matrix](docs/FEATURE-MATRIX.md)
* [Operational lifecycle runbook](docs/OPERATIONS.md)
* [Maintainer acceptance checklist](docs/MAINTAINER-ACCEPTANCE.md)
* [Remaining work](docs/ROADMAP.md).

## Build and test

Follow [docs/BUILD.md](docs/BUILD.md) in order to run the necessary commands for generating your Feclora ISO copy and doing the BIOS/UEFI QEMU checks

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
