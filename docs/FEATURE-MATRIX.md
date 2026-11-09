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
| Imaging | Extract partition from whole-disk image | Implemented; verified partition-table preview, age decrypt/re-encryption when source is encrypted, source signature verification and signed output when key is available | Cockpit | Automated tests |
| Imaging | Whole-disk restore layout preview | Read-only source partition map and destination capacity comparison; no automatic growth | Cockpit | Automated tests; operator validation |
| Imaging | On-demand image verification report | Manifest, trusted signature, stored SHA-256/size, age authentication, compression stream and decoded disk-size checks | Cockpit | Automated tests; operator validation |
| Deployment security | Client TLS certificate renewal | Reuses existing TLS key; exact Server approval; retains MAC, age and minisign trust; fingerprint-verified install | Cockpit + removable media | Automated tests; operator validation |
| Deployment security | TLS certificate expiry monitoring | Read-only Server/Client leaf and CA expiry status with 30-day warning threshold | Cockpit | Automated tests; operator validation |
| Deployment security | Server TLS certificate renewal | Existing CA/key retained; active deployment services block renewal; chain/SAN/key verified before atomic replacement | Cockpit | Automated tests; operator validation |
| Cloning | Local disk-to-disk | Implemented | Cockpit | Automated tests; operator validation |
| Cloning | Local partition-to-partition | Implemented | Cockpit | Automated tests; operator validation |
| Integrity | Manifest and SHA-256 | Implemented | Cockpit inventory/restore | Automated tests |
| Integrity | minisign signatures | Implemented | Cockpit local key setup/capture; extracted partition manifests signed when key available | Automated tests |
| Encryption | age artifact encryption | Implemented | Cockpit local key setup/capture | Automated tests |
| Compression | none, gzip, zstd, lz4 | Implemented | Cockpit basic choices | Automated tests/CI |
| Filesystems | Partclone-supported filesystems | Implemented with raw fallback | Cockpit | Automated tests; operator validation |
| Storage layers | LVM, LUKS, Btrfs, Stratis | Inventory/safety support varies; full-aware imaging incomplete | Inventory only | Automated tests; operator validation |
| Deployment identity | Managed CA and Server mTLS identity bootstrap | Implemented | Cockpit initial bootstrap | Automated tests; operator validation |
| Deployment trust | Client inventory, MAC/signing authorization, exact-confirmation revocation | Implemented | Cockpit | Automated tests |
| Deployment trust | Age recipient export and Client-side verified refresh | Implemented; removable-media exchange | Cockpit | Automated tests |
| Deployment trust | Client certificate renewal | Key-preserving removable-media renewal primitives and Cockpit workflow | Cockpit + removable media | Automated tests; operator workflow validation |
| Deployment trust | Managed CA rotation and Server TLS keypair rotation | Server TLS keypair rotation is implemented under the existing CA with new-key/certificate validation and guarded Cockpit action; staged CA trust migration remains unimplemented | Partial | Unit/API tests; no mixed-client CA migration acceptance |
| Network boot | dnsmasq/iPXE/TFTP/Caddy | ProxyDHCP/isolated DHCP preflight and transient lifecycle implemented | Cockpit activation/shutdown; persistent network setup/diagnostics incomplete | Automated tests; operator validation |
| Remote deployment | mTLS unicast save/restore | Persistent Server/Client services, READY/ARM gating, durable journals | Cockpit workflows | Automated tests; operator validation |
| Remote deployment | UDPcast multicast restore | Engine and Server/Client receiver lifecycle integrated; switch IGMP remains external | Cockpit workflows | Automated tests; operator validation |
| Remote clone | mTLS disk-to-disk protocol | Protocol engine implemented; persistent Server/Client workflow not integrated | Not yet complete | Automated tests; operator validation |
| Repositories | Remote provider command construction | SSHFS, NFS, SMB/CIFS, WebDAV and S3/rclone argv builders | Cockpit uses SSHFS/NFS/SMB | Implemented as argv builders; provider-specific credential lifecycle remains partial | Unit tests |
| Repositories | Remote mount lifecycle | Root-only registry, private mountpoints, SSHFS/NFS/SMB mount/unmount/remove, findmnt plus provider/source/type/access-mode verification | Cockpit remote-repository tab | Partial: mount listing now distinguishes mounted from identity-verified; health/free-space, edit/test and recovery workflows remain absent | Unit tests; no live remote-server acceptance |
| Repositories | Image-engine integration | Local capture/restore and Server/Client still use configured repository roots; managed repository IDs are not yet selectable | Not exposed | Not implemented | Not yet covered end to end |
| Repositories | Protected credential lifecycle | Root-owned SSH key/known_hosts and SMB credentials are referenced and permission-checked; no provisioning/rotation; WebDAV/S3 unsupported | File paths only | Partial | Unit tests |
| Monitoring | Deployment journals and audit reconciliation | Implemented | Cockpit summaries and reconciliation | Automated tests |
| Monitoring | Per-Client disk-operation progress | Authenticated Server-side byte progress and throughput; Client-local transfer-phase byte progress; Server-side artifact-transfer telemetry pending separate channel design | Cockpit live status | Automated tests |
| Monitoring | Local long-running operation lifecycle | Append-only started/terminal operation journal and streamed request progress | Cockpit operation history; work still runs in the request lifecycle | Partial: history survives, but no detached local worker/queue, persisted phase progress, or restart reconciliation for local operations | Automated journal tests |
| UI | Cockpit React/PatternFly | Implemented | Primary interface | Frontend CI build |
| UI | Terminal diagnostics | Cockpit component | Available in Cockpit | Operator validation |

Do not infer support from a package being installed. Hardware, firmware,
filesystem and network support must be verified on the actual target. ISO
creation and laboratory validation are operator-owned steps.
