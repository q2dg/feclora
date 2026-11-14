## Feclora is...

...a Live ISO running on a Fedora Server 45 (x86_64) system which automatically launches a Cockpit-based web interface inside a locked-down Firefox kiosk. The Live session is ephemeral, so credentials, certificates and temporary configuration are regenerated at boot; however, images and other durable artifacts can be stored in repositories selected by the operator.

More details:

* Feclora can clone whole local disks (or partitions) inside a lone computer or through network nodes (in a point-to-point or multicast mode). 

* Feclora can also create images, which can be stored locally or in a remote SSHFS, NFS, SMB/CIFS or S3 server (and restored from them, in a point-to-point or multicast mode too). Notice these remote servers should be implemented by the operator independently 

* Feclora also has a PXE mode in order to boot network clients to be restored without having to boot them using any Feclora ISO. 

* All restoration workflows (local, unicast or multicast) have the ability to be automated thanks to the addition of an answer file

* Ext4, XFS, Btrfs, F2FS, NTFS, ExFAT, FAT32, Stratis and LVM file systems are recognized natively to be cloned/imaged; other ones will be managed as "raw". However, note multi-device Btrfs imaging, snapshot-assisted storage capture and several advanced LUKS/LVM workflows are not supported.

* Feclora offers compression, SHA-256 integrity verification and optional age-based encryption for created images

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
