# Remote image repositories

feclora keeps its image engines independent of transport by using ordinary
filesystem paths as repository roots. Provider adapters mount remote storage;
manifests, compression, encryption, checksums and restore code continue to use
the same repository API.

## Provider contract

| Provider | Helper | Authentication material |
|---|---|---|
| SSH filesystem | sshfs | Dedicated SSH private key; verified host keys |
| NFS | mount.nfs, NFSv4.2 | Server/export policy |
| SMB/CIFS | mount.cifs, SMB 3.1.1 | Protected credentials file |
| WebDAV | mount.davfs over HTTPS | davfs2 protected secrets store |
| S3 | rclone mount | Protected rclone config or credential chain |

The provider definitions in src/feclora/storage/repository.py validate
provider inputs, reject unsafe path characters and parent traversal, and
build argument vectors without invoking a shell. The root-only lifecycle in
src/feclora/storage/repository_manager.py now persists SSHFS, NFS and SMB/CIFS
definitions in a mode-0600 registry, creates private mountpoints, checks
root-owned credential references, invokes helpers without a shell, verifies
the exact mountpoint with findmnt, verifies the mounted source/type/access mode against the saved provider definition (including in the repository listing), and exposes mount/unmount/remove actions
through Cockpit. Cockpit never receives or stores credential contents.

This is a mount-management foundation, not yet a complete image-repository
integration: capture/restore and Server/Client deployment still use their
configured repository roots and do not select these repository IDs. WebDAV
and S3/rclone are deliberately rejected by the lifecycle manager pending
their dedicated credential handling.

## Security and durability requirements

- SSH host keys must be verified; never disable strict host-key checking.
- SSH keys, SMB credentials, davfs2 secrets and rclone credentials must be
  stored outside image manifests and restore profiles with restrictive
  ownership and permissions.
- WebDAV requires HTTPS. S3 endpoint and credentials are configured in the
  protected rclone remote.
- NFS/SMB/SSHFS/WebDAV/S3 are storage transports, not PXE deployment
  transports. PXE Server/Client services remain explicit opt-in features.
- Before using a mount for imaging, runtime code must verify the expected
  provider/source identity, reject symlinked paths, and test
  write/read/rename/fsync behavior. Current mount-state inspection verifies
  the mountpoint; provider/source identity and remote publication durability
  remain to be completed before imaging can consume managed mounts.
- A mount failure must never fall back to the local directory underneath an
  unmounted mountpoint.
- Image artifacts must be staged on the same filesystem and the manifest
  published last. A remote backend must demonstrate the required atomicity
  and durability semantics before it can be used for production captures.
- S3 object storage must not be assumed to provide POSIX atomic rename or
  fsync semantics merely because rclone exposes a mount. It needs a
  provider-aware staging and publish protocol with remote read-back.

## Remaining work

Remaining work: connect repository IDs to capture/restore and Server/Client
job configuration; add edit/test and health/free-space workflows; verify
provider/source identity rather than mountpoint alone; test remote
write/read/rename/fsync and manifest publication semantics; implement
credential provisioning/rotation and recovery; add WebDAV and S3/rclone
credential integrations; and run integration tests against real SSH, NFS,
SMB, WebDAV and S3 endpoints. SFTP file transfer is distinct from SSHFS and
is not currently a mounted repository provider.
