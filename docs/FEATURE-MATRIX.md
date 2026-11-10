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
| Deployment trust | Managed CA bootstrap, enrollment/renewal, trust inventory/revocation and Server TLS keypair rotation under the existing CA | Managed CA bootstrap and Client enrollment/renewal; Server leaf renewal and keypair rotation under the existing CA; encrypted age-protected removable-media CA backup with non-destructive Cockpit verification. Broader CA rotation, migration and backup restore are deferred/not implemented | Partial | Unit/API tests; no CA migration or backup-restore acceptance |
| Network boot | dnsmasq/iPXE/TFTP/Caddy | ProxyDHCP/isolated DHCP preflight and transient lifecycle implemented | Cockpit activation/shutdown; persistent network setup/diagnostics incomplete | Automated tests; operator validation |
| Remote deployment | mTLS unicast save/restore | Persistent Server/Client services, READY/ARM gating, durable journals | Cockpit workflows | Automated tests; operator validation |
| Remote deployment | UDPcast multicast restore | Engine and Server/Client receiver lifecycle integrated; job supports multiple enrolled READY Clients; image source may be local or selected verified managed repository; switch IGMP remains external | Cockpit workflows | Automated tests; operator validation |
| Remote clone | mTLS disk-to-disk protocol | Direct whole-disk clone integrated into existing persistent Server/Client job lifecycle and Cockpit; reuses enrolled mTLS session and durable job journal | Cockpit job workflow | Automated tests; two-machine hardware validation pending |
| Repositories | Remote provider command construction | SSHFS, NFS, SMB/CIFS, WebDAV and S3/rclone mount argv builders; initial standalone OpenSSH SFTP file-transfer adapter | Cockpit uses SSHFS/NFS/SMB | Implemented as argv builders; provider-specific credential lifecycle remains partial | Unit tests |
| Repositories | Remote mount lifecycle | Root-only registry, private mountpoints, SSHFS/NFS/SMB mount/unmount/remove, findmnt plus provider/source/type/access-mode verification | Cockpit remote-repository tab | Partial: Cockpit supports add/edit while unmounted, explicit current-mount identity checks, mount/unmount/remove and mounted-vs-verified status; free-space telemetry, provider connectivity probes and recovery automation remain pending | Unit tests added; no live remote-server acceptance |
| Repositories | Image-engine integration | Cockpit selects a mounted, verified repository; backend exposes its manifest inventory and routes whole-disk/partition capture, restore, verification, layout inspection and partition extraction through the verified mount. Writes require read/write mounts; local repository remains the default | Cockpit image workflow and repository inventory | API/unit tests; remote-server round-trip and NFS root-squash acceptance remain pending |
| Repositories | Protected credential lifecycle | Host-bound systemd-creds store; Cockpit imports root-owned private source files, lists/removes encrypted references, and selects SSH key/known_hosts, SMB and rclone credentials for repository definitions; plaintext never enters browser/API responses | Cockpit encrypted credential inventory/import/removal and repository selection | Partial: SFTP adapter, synchronous systemd credential runner and signed image-set publish/fetch primitives exist (minisign before artifact retrieval, SHA-256/size verification and manifest-last no-overwrite import into the native local image-repository layout); SFTP exposes one-shot Cockpit/API signed-image import/publication and optional automatic post-capture publication for signed disk/partition captures, using encrypted SSH-key/known_hosts references and local signing trust; Cockpit can list validated manifest markers in one configured remote directory (without authenticating the manifest until import); multi-directory discovery, saved SFTP repository definitions, direct restore-job routing, transfer progress/cancel/retry/resume and full provider acceptance remain pending; WebDAV per-repository credentials and live provider acceptance remain pending | Unit tests added; not executed in this work session |
| Monitoring | Deployment journals and audit reconciliation | Implemented | Cockpit summaries and reconciliation | Automated tests |
| Monitoring | Per-Client disk-operation progress | Authenticated Server-side byte progress and throughput; Client-local transfer-phase byte progress; Server-side artifact-transfer telemetry pending separate channel design | Cockpit live status | Automated tests |
| Monitoring | Local long-running operation lifecycle | Versioned durable queue, root-owned systemd worker, hash-chained append-only journal, byte-progress checkpoints, boot-time interrupted-job recovery and process-independent block-device locks | Cockpit submits jobs and displays durable status, progress and event history | Partial: phase/throughput telemetry, export, detached-worker supervision and live systemd/hardware acceptance remain pending; interrupted writes are never resumed | Unit/API tests and CI; no live systemd or hardware acceptance |
| UI | Cockpit React/PatternFly | Implemented | Primary interface | Frontend CI build |
| UI | Terminal diagnostics | Cockpit component | Available in Cockpit | Operator validation |

Do not infer support from a package being installed. Hardware, firmware,
filesystem and network support must be verified on the actual target. ISO
creation and laboratory validation are operator-owned steps.
