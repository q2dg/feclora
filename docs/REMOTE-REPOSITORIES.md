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
src/feclora/storage/repository_manager.py persists all five provider
definitions in a mode-0600 registry, creates private mountpoints, checks
root-owned credential references, invokes helpers without a shell, verifies
the exact mountpoint with findmnt, and checks the mounted source, filesystem
type and access mode against the saved definition. Cockpit exposes
add/mount/unmount/remove and never receives credential contents. Existing
registry entries created before the rclone_remote field was introduced remain
readable.

WebDAV uses HTTPS and the system davfs2 secrets file at
/etc/davfs2/secrets (root-owned, mode 0600); that file must contain the
matching URL, username and password entry. S3 uses a preconfigured rclone
remote alias and a separate root-owned mode-0600 rclone config file. The
endpoint, bucket credentials and provider-specific settings belong in that
rclone remote, not in Feclora's registry. S3 repositories are deliberately
read-only: rclone's FUSE mount does not provide the provider-aware staging,
atomic publication and durability contract required for safe image capture.

## Credential architecture transition

Fedora's `oo7-daemon` implements the Secret Service D-Bus API for an
interactive user session. It is suitable for secrets owned by an operator
session, but it is not a machine-wide root secret broker: a headless Server
job must not depend on an operator's user bus, unlocked keyring or browser
session. In particular, a Cockpit request must never pass secret bytes through
the browser to bridge this session boundary.

For persistent Server-side work, Feclora is adopting systemd's native
encrypted service credentials. `systemd-creds` encrypts credential payloads
against the local system credential key (and TPM2 where available); the
resulting blobs are intended for `LoadCredentialEncrypted=` on the specific
systemd service that consumes them. Plaintext is made available only in that
service's private credential directory at activation. This supports jobs that
continue after Cockpit disconnects and does not require an interactive
operator session. See [ADR 0011](adr/0011-secret-service-and-systemd-credentials.md).

The new `SystemdCredentialStore` is the first implementation step: it writes
host-bound encrypted blobs under `/etc/credstore.encrypted/feclora`, imports
plaintext only over the `systemd-creds` stdin interface, and returns
metadata/references rather than secret contents. **It is not yet wired into
repository mount units or the Cockpit credential workflow.** The existing
plaintext `CredentialStore` and CLI are retained temporarily for compatibility
and migration; do not treat them as the final Server credential architecture.
Until per-repository systemd mount/service units consume
`LoadCredentialEncrypted=`, existing repository credential references still
use the legacy protected-file mechanism.

## Local credential provisioning primitive

`feclora.storage.credential_store.CredentialStore` provides a root-only
administrative primitive for storing SSH private keys, SSH known-hosts files,
SMB credential files and rclone configurations under
`/etc/feclora/credentials`. It writes atomically, defaults to create-only,
requires an explicit replace operation to update an existing credential, and
validates ownership, link count and permissions before replacement or removal.
The returned value is only a filesystem reference; secret contents are never
returned or copied into the repository registry.

The local CLI is invoked as root with
`python3 -m feclora.storage.credential_cli put --id nas --kind ssh-key --source /root/secure/nas.key`.
The source must itself be a root-owned private regular file, not a symlink or
hard link. Add `--replace` only when intentionally rotating the stored file.
Use `python3 -m feclora.storage.credential_cli remove --id nas --kind ssh-key`
to remove it. The command prints only the resulting reference path, never the
secret. Cockpit's `remote_credentials` API action lists validated references
only; it never accepts or returns secret contents. Cockpit selection and
repository edit workflows are not yet implemented. WebDAV continues to
use the separately managed `/etc/davfs2/secrets` file. Existing repository
definitions must be updated to reference the resulting protected file paths.

## Host dependencies

On Fedora, install the helpers required by the providers you intend to use:

```bash
sudo dnf install fuse-sshfs nfs-utils cifs-utils davfs2 rclone
```

Only the selected provider's helper is needed. The manager checks for the
required executable before attempting a mount. The S3 rclone config must be
created and provisioned separately; Feclora does not collect access keys or
run the interactive rclone configuration wizard.

## Security and durability requirements

- SSH host keys must be verified; never disable strict host-key checking.
- SSH keys, SMB credentials, davfs2 secrets and rclone credentials must be
  stored outside image manifests and restore profiles with restrictive
  ownership and permissions. Cockpit accepts paths/aliases, never secret
  contents.
- WebDAV requires HTTPS and the root-only /etc/davfs2/secrets file.
- S3 requires a root-owned mode-0600 rclone config and an existing remote
  alias configured for the intended S3-compatible service. The config file
  must be available non-interactively to the root rclone process.
- NFS/SMB/SSHFS/WebDAV/S3 are storage transports, not PXE deployment
  transports. PXE Server/Client services remain explicit opt-in features.
- Runtime resolves repository IDs through the manager and checks the
  expected mount source/type/access mode. A failed or mismatched mount never
  falls back to the local directory underneath the mountpoint.
- A remote restore holds a shared, root-managed usage lease for the
  lifetime of its persistent Server service. Unmount takes an exclusive
  non-blocking lease and is refused while a restore service holds the
  repository. Removing its registry definition takes the same exclusive lease,
  so a vanished mount cannot make an active restore lose its repository
  configuration. The Server re-resolves and re-verifies the mount after
  acquiring its lease, closing the race between job creation and service
  startup. Stop the restore service after the job reaches a terminal state
  before unmounting or removing the definition.
- S3 is read-only until a provider-aware staging/publish protocol with remote
  read-back is implemented; do not enable capture or extraction on S3.
- A mount failure must never fall back to the local directory underneath an
  unmounted mountpoint.
- Image artifacts must be staged on the same filesystem and the manifest
  published last. A remote backend must demonstrate the required atomicity
  and durability semantics before it can be used for production captures.
- S3 object storage must not be assumed to provide POSIX atomic rename or
  fsync semantics merely because rclone exposes a mount. It needs a
  provider-aware staging and publish protocol with remote read-back.
- A future S3 publisher must use the object API directly, not write through
  the rclone FUSE mount. Each final artifact key must be created with a
  server-enforced create-if-absent precondition (for example, conditional
  PutObject with If-None-Match: * where the provider documents support).
  A preceding HEAD/list check is not a substitute: it has a time-of-check /
  time-of-use race. Multipart uploads need an equivalent conditional
  completion guarantee; if the provider cannot guarantee it, Feclora must
  reject publication rather than silently fall back to an unconditional
  overwrite.
- Publication must use unique staging keys, verify each completed object by
  reading it back and checking byte count and cryptographic digest, then
  publish the signed manifest last with the same create-if-absent condition.
  Failed publication may leave unreachable staging objects for later
  garbage collection, but must never expose a manifest referencing
  incomplete artifacts. Provider capability checks must be explicit and
  fail closed; S3-compatible branding alone is not evidence of support.

## Remaining work

Remaining engineering work: add edit/test and health/free-space workflows,
credential provisioning/rotation and recovery, provider-aware S3 artifact
publication, and automated coverage for the remote mount lifecycle. Physical
tests against SSHFS, NFS, SMB, WebDAV and S3 endpoints are operator acceptance
tests. SFTP file transfer is distinct from SSHFS and is not a separate mounted
repository provider.


## Image workflow integration

Cockpit's Image repository tab and local capture/restore operation form can select
a configured repository only while its mount is active and verified. The API
resolves the repository ID through the manager on every operation; it does not
accept a client-supplied mount path. Whole-disk and partition capture require a
read/write mount. Restore, inventory, layout inspection and verification can
use a read-only mount. Partition extraction writes a new image and therefore
requires read/write access.

Image manifests are required to be root-owned regular files. An NFS export
using root-squash may map files created by the client root user to an anonymous
UID, causing Feclora's ownership check to reject the manifest. Do not weaken
this check; configure the export's ownership semantics accordingly. Cockpit
image operations and multi-Client restore jobs can select mounted repository
IDs. S3 remains read-only and is suitable for inventory/verification/restore,
not image capture.
