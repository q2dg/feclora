# Feature and compatibility matrix

Status meanings: `Planned`, `In progress`, `Implemented`, `Verified`, `Not supported`.

| Area | Capability | Status | Verification notes |
|---|---|---|---|
| Boot | x86_64 BIOS boot | Planned | VM smoke test |
| Boot | x86_64 UEFI boot | Planned | VM smoke test |
| Boot | Secure Boot | Not assessed | Requires signing and shim/GRUB validation |
| Storage | Block-device discovery | Planned | Include NVMe, SATA, USB and virtio |
| Storage | GPT and MBR partition tables | Planned | Test both layouts |
| Imaging | Whole-disk image create/restore | Planned | Verify checksums and restore in disposable VM |
| Imaging | Partition image create/restore | Planned | Include supported filesystem cases |
| Filesystems | ext4, XFS, Btrfs, NTFS, FAT | Not assessed | Capability depends on imaging backend |
| Compression | Compressed image streams | Planned | Measure throughput and error handling |
| Integrity | Image verification | Planned | Detect truncated and corrupted images |
| Network | SSH/SFTP transport | Planned | Authentication and host-key handling |
| Network | NFS and Samba transport | Planned | Mount lifecycle and credentials |
| Network deployment | Multicast/PXE | Planned | Later milestone |

Do not infer support from a package being installed. `Verified` requires a reproducible test and recorded environment.