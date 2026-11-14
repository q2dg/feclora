## Feclora is...

...a Live ISO running on a Fedora Server 45 (x86_64) system which automatically launches a Cockpit-based web interface inside a locked-down Firefox kiosk. The Live session is ephemeral, so credentials, certificates and temporary configuration are regenerated at boot; however, images and other durable artifacts can be stored in repositories selected by the operator.

More details:

* Feclora can clone whole local disks (or partitions) inside a lone computer or through network nodes (in a point-to-point or multicast mode). 

* Feclora can also create images, which can be stored locally or in a remote SSHFS, NFS, SMB/CIFS or S3 server (and restored from them, in a point-to-point or multicast mode too). Notice these remote servers should be implemented by the operator independently 

* Feclora also has a PXE mode in order to boot network clients to be restored without having to boot them using any locally-inserted Feclora ISO. 

* Unattended whole-disk restoration is supported for multicast network clients through a declarative answer file. Local and network unicast unattended jobs use automated restore profiles

* Filesystem-aware imaging supports ext2/3/4, XFS, NTFS, FAT variants, exFAT and F2FS, plus supported single-device Btrfs partition images, when the required utilities are available. Unknown or unsupported content is handled as raw where safe. LVM logical volumes and raw LUKS2 containers are supported image sources under documented restrictions; Stratis is inventoried but is not a fully supported imaging target. Coordinated multi-device Btrfs imaging and snapshot-assisted capture are not supported

* Feclora offers compression, SHA-256 integrity verification and optional age-based encryption for created images

## Built on

Feclora brings together the following projects and tools:

* [Fedora Server](https://fedoraproject.org/server/) — Live operating-system base.
* [Cockpit](https://cockpit-project.org/) — web-based system administration interface.
* [Firefox](https://www.mozilla.org/firefox/) and [Cage](https://github.com/cage-kiosk/cage) — locked-down graphical kiosk.
* [Partclone](https://partclone.org/) — filesystem-aware partition imaging.
* [Lorax](https://weldr.io/lorax/) — Live ISO construction.
* [QEMU/KVM](https://www.qemu.org/) — virtualized ISO build and validation.
* [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html) and [iPXE](https://ipxe.org/) — network boot and DHCP/PXE services.
* [Caddy](https://caddyserver.com/) — HTTP delivery of PXE boot assets and answer files.
* [UDPcast](https://www.udpcast.linux.lu/) — multicast image distribution.
* [NetworkManager](https://networkmanager.dev/) — network configuration and DHCP lease discovery.
* [age](https://age-encryption.org/) — optional image encryption.
* [zstd](https://facebook.github.io/zstd/) and [LZ4](https://lz4.github.io/lz4/) — image compression.
* [LVM2](https://sourceware.org/lvm2/) and [Stratis](https://stratis-storage.github.io/) — storage discovery and logical-volume support.
* [cryptsetup](https://gitlab.com/cryptsetup/cryptsetup) — LUKS container handling.


## Documentation

Start with these [step-by-step operator guides](https://q2dg.github.io/feclora/GETTING-STARTED.html).

You can also read these other documents:

* [operator guides](docs/GUIDES.md)
* [feature matrix](docs/FEATURE-MATRIX.md)
* [build instructions](docs/BUILD.md)
* [operational lifecycle runbook](docs/OPERATIONS.md)
* [maintainer acceptance checklist](docs/MAINTAINER-ACCEPTANCE.md)
* [remaining work](docs/ROADMAP.md).

## Build and test

Follow [docs/BUILD.md](docs/BUILD.md) for build-host prerequisites, run ISO generation commands and do BIOS/UEFI QEMU checks.

## License

GNU General Public License v3.0 or later. See [LICENSE](LICENSE).
