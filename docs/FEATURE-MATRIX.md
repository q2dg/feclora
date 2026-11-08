# Feature and compatibility matrix

Status meanings:
- **Implemented**: code path exists.
- **Cockpit**: exposed through the primary web interface.
- **Automated**: covered by hardware-independent tests or CI checks.
- **Operator validation**: requires ISO boot, physical media, network equipment or laboratory machines.

| Area | Capability | Implementation | Cockpit | Verification |
|---|---|---|---|---|
| Boot | x86_64 BIOS | Build configuration present | N/A | Operator validation |
| Boot | x86_64 UEFI | Build configuration present | N/A | Operator validation |
| Storage | Block-device and partition inventory | Implemented | Cockpit | Automated tests |
| Imaging | Whole-disk capture/restore | Implemented | Cockpit | Automated tests; operator validation |
| Imaging | Partition capture/restore | Implemented | Cockpit | Automated tests; operator validation |
| Cloning | Disk-to-disk | Implemented | Cockpit | Automated tests; operator validation |
| Cloning | Partition-to-partition | Implemented | Cockpit | Automated tests; operator validation |
| Integrity | Manifest and SHA-256 | Implemented | Cockpit inventory/restore | Automated tests |
| Integrity | minisign signatures | Implemented | Cockpit local key setup/capture | Automated tests |
| Encryption | age artifact encryption | Implemented | Cockpit local key setup/capture | Automated tests |
| Compression | none, gzip, zstd, lz4 | Implemented | Cockpit basic choices | Automated tests/CI |
| Filesystems | Partclone-supported filesystems | Implemented with raw fallback | Cockpit | Automated tests; operator validation |
| Storage layers | LVM, LUKS, Btrfs, Stratis | Inventory/safety support varies; full-aware imaging incomplete | Inventory only | Automated tests; operator validation |
| Network boot | dnsmasq/iPXE/TFTP/Caddy | Implemented | Not yet complete | Operator validation |
| Remote deployment | mTLS unicast save/restore | Engine implemented | Not yet complete | Automated tests; operator validation |
| Remote deployment | UDPcast multicast restore | Engine implemented for disk/partition | Not yet complete | Automated tests; operator validation |
| Remote clone | mTLS disk-to-disk protocol | Engine implemented | Not yet complete | Automated tests; operator validation |
| Monitoring | Deployment journals | Implemented | Read-only summaries | Automated tests |
| Monitoring | Per-client live progress | Partial | Not yet complete | Outstanding |
| UI | Cockpit React/PatternFly | Implemented | Primary interface | Frontend CI build |
| UI | Terminal diagnostics | Cockpit component | Available in Cockpit | Operator validation |

Do not infer support from a package being installed. Hardware, firmware,
filesystem and network support must be verified on the actual target. ISO
creation and laboratory validation are operator-owned steps.
