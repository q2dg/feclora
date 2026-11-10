# Feature and compatibility matrix

Remote-service boundary: SSH/SFTP, NFS, SMB/CIFS, WebDAV, S3-compatible
storage and optional BitTorrent infrastructure are external systems operated
by their owners. Feclora is a client only; its implementation covers outbound
access, credentials, mounts/transfers, integrity and client-side failure
handling. It does not deploy or administer those remote services.

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
| Imaging | On-demand image verification report | Manifest, trusted signature, stored SHA-256/size, age authentication, compression stream and decoded raw disk/partition size checks | Cockpit | Automated tests; operator validation |
| Deployment security | Client TLS certificate renewal | Reuses existing TLS key; exact Server approval; retains MAC, age and minisign trust; fingerprint-verified install | Cockpit + removable media | Automated tests; operator validation |
| Deployment security | TLS certificate expiry monitoring | Read-only Server/Client leaf and CA expiry status with 30-day warning threshold | Cockpit | Automated tests; operator validation |
| Deployment security | Server TLS certificate renewal | Existing CA/key retained; active deployment services block renewal; chain/SAN/key verified before atomic replacement | Cockpit | Automated tests; operator validation |
| Cloning | Local disk-to-disk | Implemented | Cockpit | Automated tests; operator validation |
| Cloning | Local partition-to-partition | Implemented | Cockpit | Automated tests; operator validation |
| Integrity | Manifest and SHA-256 | Implemented | Cockpit inventory/restore | Automated tests |
| Integrity | Optional detached signatures (`minisign` implementation) | Implemented as optional integration; absence must not block baseline local imaging | Cockpit capture/verification when configured | Automated tests; real Fedora Live acceptance pending |
| Encryption | Optional artifact encryption (`age` implementation) | Implemented as optional integration; absence must not block baseline local imaging | Cockpit capture/restore when configured | Automated tests; real Fedora Live acceptance pending |
| Compression | none, gzip, xz, zstd, lz4 | Implemented | Cockpit basic choices | Automated tests/CI |
| Filesystems | Partclone-supported filesystems | Implemented with raw fallback; native current/total block progress is consumed from stderr on legacy builds and native JSON byte counters are used when the installed Partclone advertises `--json-status` | Cockpit | Automated tests; operator validation |
| Storage layers | LVM, LUKS, Btrfs, Stratis | Inventory/safety support varies; full-aware imaging incomplete | Inventory only | Automated tests; operator validation |
| Deployment identity | Managed CA and Server mTLS identity bootstrap | Implemented | Cockpit initial bootstrap | Automated tests; operator validation |
| Deployment trust | Client TLS identity/MAC authorization and exact-confirmation revocation | Implemented | Cockpit | Automated tests |
| Deployment trust | Optional Client minisign public-key enrollment for signed image capture | Implemented; unsigned Client capture remains permitted | Cockpit | Automated tests; Fedora Live acceptance pending |
| Deployment trust | Optional age recipient export and Client-side verified refresh | Implemented when age encryption is configured; removable-media exchange | Cockpit | Automated tests |
| Deployment trust | Client certificate renewal | Key-preserving removable-media renewal primitives and Cockpit workflow | Cockpit + removable media | Automated tests; operator workflow validation |
| Deployment trust | Managed CA bootstrap, enrollment/renewal, trust inventory/revocation and Server TLS keypair rotation under the existing CA | Managed CA bootstrap and Client enrollment/renewal; Server leaf renewal and keypair rotation under the existing CA; encrypted age-protected removable-media CA backup with non-destructive Cockpit verification. Broader CA rotation, migration and backup restore are deferred/not implemented | Partial | Unit/API tests; no CA migration or backup-restore acceptance |
| Network boot | dnsmasq/iPXE/TFTP/Caddy | ProxyDHCP/isolated DHCP preflight and transient lifecycle implemented | Cockpit activation/shutdown; persistent network setup/diagnostics incomplete | Automated tests; operator validation |
| Remote deployment | mTLS unicast save/restore | Persistent Server/Client services, READY/ARM gating, durable journals; Client save asks per image whether to use age encryption and/or minisign signing, default off | Cockpit workflows | Automated tests; operator validation |
| Remote deployment | UDPcast multicast restore | Engine and Server/Client receiver lifecycle integrated; job supports multiple enrolled READY Clients; image source may be local or selected verified managed repository; switch IGMP remains external | Cockpit workflows | Automated tests; operator validation |
| Remote clone | mTLS disk-to-disk protocol | Direct whole-disk clone integrated into existing persistent Server/Client job lifecycle and Cockpit; reuses enrolled mTLS session and durable job journal | Cockpit job workflow | Automated tests; two-machine hardware validation pending |
| Repositories | Provider transport and mount construction | SSHFS, NFS, SMB/CIFS and read-only S3/rclone mount adapters; OpenSSH SFTP transfer adapter; WebDAV rejected pending isolated credentials | Cockpit uses SSHFS/NFS/SMB and read-only S3; SFTP is a separate signed file-transfer workflow | Partial: mount argv support is not provider acceptance; WebDAV unavailable, S3 writable publication blocked, SFTP transfer lifecycle incomplete | Unit tests; live provider acceptance pending |
| Repositories | Remote mount lifecycle | Root-only registry with cross-process serialized add/update/remove transactions, private mountpoints, SSHFS/NFS/SMB mount/unmount/remove, findmnt plus provider/source/type/access-mode identity verification | Cockpit remote-repository tab | Partial across all mounted providers: `verified` means only findmnt source/type/access-mode identity matches the saved definition; no live connectivity, I/O, latency, free-space or quota probe is performed. Stale-mount recovery, provider health probes, outage behavior and concurrent-writer acceptance remain pending; the findmnt identity query is bounded to five seconds and fails closed on timeout/malformed output, but is not a network health probe; NFS root-squash is a specific gate | Unit tests cover concurrent-add preservation, symlinked-lock rejection, failed-removal rollback, bounded findmnt timeout and malformed identity output; not run in this work session; no live remote-server acceptance |
| Repositories | Mounted-provider image-engine integration | Common image engine uses verified SSHFS/NFS/SMB mounts for inventory, capture, restore, verification, layout inspection and partition extraction; S3 mount is read-only for inventory/restore | Cockpit image workflow and repository inventory | Software integration exists, but end-to-end capture/restore, permission, interruption, cleanup and NFS root-squash acceptance are pending per provider; S3 capture is deliberately blocked |
| Repositories | Protected credential lifecycle | Host-bound systemd-creds store; Cockpit imports root-owned private source files, lists/removes encrypted references, and selects SSH key/known_hosts, SMB and rclone credentials for repository definitions; plaintext never enters browser/API responses | Cockpit encrypted credential inventory/import/removal and repository selection | Partial: SFTP adapter, synchronous systemd credential runner and signed image-set publish/fetch primitives exist (current implementation uses minisign before artifact retrieval, plus SHA-256/size verification and manifest-last no-overwrite import into the native local image-repository layout; configurable verifier/alternative trust remains required to make minisign optional); SFTP exposes one-shot Cockpit/API signed-image import/publication and optional automatic post-capture publication for signed disk/partition captures, using encrypted SSH-key/known_hosts references and current minisign-based local signing trust; Cockpit can list validated manifest markers and authenticate/preview the signed manifest metadata in one configured remote directory before artifact import; direct restore-job routing is now integrated with authenticated manifest ID/SHA-256 binding and artifact verification before restore; saved named SFTP endpoint definitions with encrypted credential references are integrated; multi-directory discovery, byte-level transfer progress, resume and full provider acceptance remain pending; remote manifest-marker inventory now runs as a durable/cancellable Cockpit local operation, while metadata inspection and artifact import/publication are still synchronous; bounded retries apply only to transient download/inventory failures, not uploads; WebDAV per-repository credentials and live provider acceptance remain pending | Unit tests added; not executed in this work session |
| Monitoring | Deployment journals and audit reconciliation | Implemented | Cockpit summaries and reconciliation | Automated tests |
| Monitoring | Per-Client disk-operation progress | Authenticated Server-side byte progress and throughput; Client-local transfer-phase byte progress; Server-side artifact-transfer telemetry pending separate channel design | Cockpit live status | Automated tests |
| Monitoring | Local long-running operation lifecycle | Versioned durable queue, root-owned systemd worker, hash-chained append-only journal, byte-progress checkpoints, boot-time interrupted-job recovery, process-independent block-device locks, SIGTERM-driven cancellation and bounded child-process shutdown | Cockpit submits jobs, displays durable status/progress/history and can request cancellation | Partial: phase/throughput telemetry, export, detached-worker supervision and live systemd/hardware acceptance remain pending; cancelled restores/clones may leave partially written destinations and require inspection | Unit/API tests added; not executed in this work session; no live systemd or hardware acceptance |
| UI | Cockpit React/PatternFly | Implemented | Primary interface | Frontend CI build |
| UI | Terminal diagnostics | Cockpit component | Available in Cockpit | Operator validation |

Do not infer support from a package being installed. Hardware, firmware,
filesystem and network support must be verified on the actual target. ISO
creation and laboratory validation are operator-owned steps.


## Optional distribution transports

| Area | Capability | Implementation | Cockpit | Verification |
|---|---|---|---|---|
| Distribution | BitTorrent peer-to-peer artifact delivery | Planned optional immutable-artifact transport; must reuse a maintained client and verify trusted manifest plus SHA-256 before restore | Not implemented; not a mounted/writable repository | Not implemented; design, client integration, authorization, cancellation, cleanup and acceptance remain pending |

`age` and `minisign` are optional integrations, not mandatory runtime packages or release gates. WebDAV and S3 remain required repository types with the credential/publication limitations stated above; S3's current rclone mount is read-only. Do not mark a provider complete based solely on an argv builder or mount primitive.