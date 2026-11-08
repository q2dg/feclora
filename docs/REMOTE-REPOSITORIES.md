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

The initial implementation in src/feclora/storage/repository.py validates
provider definitions, rejects unsafe path characters and parent traversal,
and builds argument vectors without invoking a shell. It never accepts
passwords inline. The caller still owns mountpoint creation, privilege
escalation, process lifecycle, mount verification and unmount.

## Security and durability requirements

- SSH host keys must be verified; never disable strict host-key checking.
- SSH keys, SMB credentials, davfs2 secrets and rclone credentials must be
  stored outside image manifests and restore profiles with restrictive
  ownership and permissions.
- WebDAV requires HTTPS. S3 endpoint and credentials are configured in the
  protected rclone remote.
- NFS/SMB/SSHFS/WebDAV/S3 are storage transports, not PXE deployment
  transports. PXE Server/Client services remain explicit opt-in features.
- Before using a mount, runtime code must verify that the expected mount is
  active, reject symlinked paths, and test write/read/rename/fsync behavior.
- A mount failure must never fall back to the local directory underneath an
  unmounted mountpoint.
- Image artifacts must be staged on the same filesystem and the manifest
  published last. A remote backend must demonstrate the required atomicity
  and durability semantics before it can be used for production captures.
- S3 object storage must not be assumed to provide POSIX atomic rename or
  fsync semantics merely because rclone exposes a mount. It needs a
  provider-aware staging and publish protocol with remote read-back.

## Remaining work

The current command builders are not a complete storage integration. Still
required: dependency packaging and availability detection, protected
credential provisioning, mount/unmount lifecycle management, active-mount
identity checks, remote write/read/rename verification, interruption recovery,
and integration tests against real SSH, NFS, SMB, WebDAV and S3 endpoints.
