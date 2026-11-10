# Remote image repositories

feclora keeps its image engines independent of transport by using ordinary
filesystem paths as repository roots. Provider adapters mount remote storage;
manifests, compression, encryption, checksums and restore code continue to use
the same repository API.

## Provider contract

SFTP is intentionally not represented as a mounted filesystem provider. Feclora has an initial OpenSSH SFTP file-transfer adapter with pinned host keys, encrypted systemd credential execution, no-overwrite hard-link publication, and signed image-set publish/fetch primitives. These are transfer primitives only: SFTP is not yet exposed as a Cockpit provider or connected to capture/restore job orchestration, durable progress, resume/retry or end-user repository discovery. SSHFS mounts do not satisfy the SFTP transfer contract.

| Provider | Helper | Authentication material |
|---|---|---|
| SSH filesystem | sshfs | Dedicated SSH private key; verified host keys |
| SFTP | OpenSSH SFTP batch adapter and signed image-set transfer primitives | Registered encrypted SSH key and known_hosts references loaded by transient systemd credentials; Cockpit provider workflow pending |
| NFS | mount.nfs, NFSv4.2 | Server/export policy |
| SMB/CIFS | mount.cifs, SMB 3.1.1 | Protected credentials file |
| WebDAV | mount.davfs over HTTPS | System-wide `/etc/davfs2/secrets` for root mounts; encrypted Feclora credential integration blocked |
| S3 | rclone mount | Protected rclone config or credential chain |

The provider definitions in src/feclora/storage/repository.py validate
provider inputs, reject unsafe path characters and parent traversal, and
build argument vectors without invoking a shell. The root-only lifecycle in
src/feclora/storage/repository_manager.py persists all five provider
definitions in a mode-0600 registry, creates private mountpoints, checks
root-owned credential references, invokes helpers without a shell, verifies
the exact mountpoint with findmnt, and checks the mounted source, filesystem
type and access mode against the saved definition. Cockpit exposes
add/edit/check/mount/unmount/remove and never receives credential contents. Existing
registry entries created before the rclone_remote field was introduced remain
readable.

WebDAV uses HTTPS and, for the current root-invoked mount path, davfs2 reads
its system-wide `/etc/davfs2/secrets` file (root-owned, mode 0600); that file
must contain the matching URL, username and password entry. Feclora rejects
systemd-encrypted credential references for WebDAV rather than silently
ignoring them: upstream davfs2 documents `secrets` as a per-user configuration
setting, while root mounts always use the system-wide secrets file. A safe
per-repository WebDAV design therefore needs a deliberate non-root davfs2
configuration/daemon model; it must not write credentials into the global file
or claim that `LoadCredentialEncrypted=` is already integrated. See the
[davfs2 configuration manual](https://manpages.debian.org/unstable/davfs2/davfs2.conf.5.en.html).

S3 uses a preconfigured rclone
remote alias and a separate root-owned mode-0600 rclone config file. The
endpoint, bucket credentials and provider-specific settings belong in that
rclone remote, not in Feclora's registry. S3 repositories are deliberately
read-only: rclone's FUSE mount does not provide the provider-aware staging,
atomic publication and durability contract required for safe image capture.

## Cockpit credential workflow

1. Prepare each source file on the Feclora host. It must be a root-owned regular
   file, mode 0600, with no symlink or hard link, between 1 byte and 1 MiB.
   This applies to `known_hosts` files too. Do not paste secret material into
   Cockpit fields or command arguments.
2. In Cockpit, open **Remote repositories → Encrypted repository credentials**.
   Enter a credential ID, select SSH private key, SSH `known_hosts`, SMB
   credentials or rclone config, and enter the protected source-file path.
   Import encrypts the file locally; the browser sends only the path and receives
   only metadata. Feclora leaves the source file in place.
3. Create the repository definition and select the imported encrypted
   credential references in the provider-specific fields. SSHFS requires both
   a private key and pinned `known_hosts` entry; SMB requires an SMB file;
   S3 requires an rclone config and is forced read-only. NFS needs no credential.
4. Mount and verify the repository. A credential cannot be removed while any
   saved repository references it. To rotate one, import with **Replace**, then
   unmount and remount each affected repository so its service loads the new
   encrypted credential. Existing mount processes retain the credential they
   received at activation.

The encrypted blobs are bound to the local system credential key. They are not
portable backup files; plan credential reprovisioning when moving a repository
to another Server or recovering after loss of its host/TPM credential key.

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

The `SystemdCredentialStore` writes host-bound encrypted blobs under
`/etc/credstore.encrypted/feclora`, imports plaintext only over the
`systemd-creds` stdin interface, and returns metadata/references rather than
secret contents. The repository manager now detects registered encrypted
credential paths for SSHFS identity keys and pinned `known_hosts` files, SMB credential
files and rclone configurations. It launches a transient per-repository systemd service with
`LoadCredentialEncrypted=`; the mount helper reads the decrypted file only
from that service's `$CREDENTIALS_DIRECTORY`. SSHFS and rclone stay in the
foreground under the service, and unmount stops the service before falling
back to an explicit unmount where needed.

The mount service intentionally does not enable systemd filesystem namespace
isolation: doing so would make its mount namespace private and hide the mount
from Feclora's other services. It runs as root with `NoNewPrivileges=` and a
restrictive umask; the encrypted credential itself is exposed only through
systemd's service credential directory. This is a deliberate mount-propagation
trade-off and should be revisited if a dedicated mount-namespace propagation
design is introduced.

This integration now exposes Cockpit import/removal and selection of encrypted
SSH private keys, SSH `known_hosts`, SMB credentials and rclone configuration.
The operator supplies only a path to a root-owned private source file; the API
reads it locally, encrypts it through `systemd-creds`, and returns metadata.
The source file is not deleted by Feclora. Repository definitions reference the
encrypted blob path, and the mount service receives it through
`LoadCredentialEncrypted=`. NFS does not require credentials. WebDAV remains
unavailable through the Cockpit/API path until a per-repository encrypted
credential design is implemented; the global `/etc/davfs2/secrets` file is not
used as a workaround. SFTP remains a separate transfer provider whose image-set primitives are not yet integrated into Cockpit capture/restore workflows.
Existing plaintext
`CredentialStore` and CLI paths remain temporarily supported for migration;
they are not the target architecture.

The encrypted store can be provisioned locally (as root) from a root-owned,
mode-0600 source file:

```bash
sudo python3 -m feclora.storage.systemd_credential_cli put \
  --id nas --kind ssh-key --source /root/secure/nas.key
sudo python3 -m feclora.storage.systemd_credential_cli put \
  --id nas --kind ssh-key --source /root/secure/nas.key --replace
sudo python3 -m feclora.storage.systemd_credential_cli remove \
  --id nas --kind ssh-key
```

The command prints only the encrypted blob path. Use that path as the
`identity_file` for SSHFS, or as `credential_file` for SMB and S3 repository
definitions. The manager derives the credential name from the validated
inventory and supplies `LoadCredentialEncrypted=` to the transient mount
service. The helper substitutes the corresponding
`$CREDENTIALS_DIRECTORY/name` path into the provider command; no plaintext
credential path is persisted in the repository registry. The privileged
`systemd_credentials` API action exposes validated metadata only; it does
not expose plaintext or create/update credentials through Cockpit.

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
repository editing is available only while unmounted; the check action verifies the current mount identity but does not probe provider write access, latency or free space. WebDAV continues to
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


## SFTP transfer adapter status

The initial adapter provides `upload_file` and `download_file` for individual
regular files. It uses OpenSSH SFTP in batch mode with `-F /dev/null`,
`BatchMode=yes`, `IdentitiesOnly=yes`, `StrictHostKeyChecking=yes`, an
explicit `UserKnownHostsFile`, and an explicit identity file. It does not
accept passwords, invoke a shell, or consult the operator's SSH configuration.
Upload first writes a random hidden staging name and then creates the final name with the OpenSSH SFTP hard-link extension (which fails if the destination exists), removing the staging name only after success;
download writes to a random sibling temporary file, checks the caller-supplied
SHA-256 (normally obtained from a signed Feclora manifest), and publishes with
a no-overwrite hard link.

The adapter now has a companion runner, `sftp_transfer_service.py`, which resolves the registered `ssh-key` and `known-hosts` encrypted credential references and executes the transfer in a synchronous transient systemd service using `LoadCredentialEncrypted=`. Plaintext credentials exist only in that service's private `CREDENTIALS_DIRECTORY`; the API-side invocation contains only encrypted blob paths and non-secret transfer parameters. This runner is callable as a Python service helper but is not yet exposed as a Cockpit action or wired into image capture/restore operation orchestration.\n\nThis is deliberately not marked as a complete SFTP repository provider.
OpenSSH SFTP does not provide a portable server-side SHA-256 operation, so the
upload adapter returns the locally computed digest and relies on the signed
manifest verification when the artifact is later consumed. The current
adapter has no resume protocol, artifact-set transaction, Cockpit form/API,
credential import binding, operation-journal progress, or capture/restore
routing. Those remain acceptance blockers. Do not select SSHFS when SFTP
transfer semantics are required, and do not infer Cockpit SFTP support from
the presence of this module.


### Signed SFTP image-set publication primitive

`sftp_image_set.py` adds a standalone publisher for the existing manifest v1
format. Before any network transfer it parses the manifest, verifies the
detached minisign signature against a separately supplied trusted public key,
and checks every local artifact's regular-file type, byte count and SHA-256
against the signed manifest. It then uploads each artifact, followed by
`manifest.json`, and uploads `manifest.json.minisig` last. The signature is
the publication marker: a consumer must not accept a set without downloading
and verifying both metadata files and independently checking every artifact.

Each individual upload retains the adapter's random staging name and uses the
OpenSSH hard-link extension for atomic no-overwrite publication; servers that
do not support that extension fail closed. This is not a multi-file atomic transaction:
failed publication can leave unreferenced remote artifacts or a manifest
without its signature. Such a set is incomplete and must be rejected. The
publisher does not yet implement remote inventory/garbage collection,
download-side manifest discovery, operation-journal progress, Cockpit actions,
or capture/restore routing. It is an integration primitive, not end-user SFTP
support; SFTP remains outside the complete provider acceptance gate.


The same module now includes `fetch_image_set()`. It downloads only
`manifest.json` and `manifest.json.minisig` in explicitly marked unverified
metadata mode into a new private staging directory. It enforces metadata size
limits, parses the existing manifest schema and verifies minisign against an
independently trusted public key before requesting any image artifact.
Artifacts are downloaded with their signed SHA-256 values, checked again for
byte count and digest, and the complete directory is published under the
manifest image ID using Linux `renameat2(RENAME_NOREPLACE)`. If atomic
no-replace directory publication is unavailable, the operation fails closed.
An existing image ID is never overwritten. Failed or invalid retrievals remove
the private staging directory.

The metadata download mode is restricted by the transient-service CLI to the
two metadata filenames; it never marks them as verified. Artifact download
results explicitly report digest verification. The destination root must
already exist and must not contain symlinked path components. The remote
directory must already exist on the SFTP server.

This provides a signed, integrity-checked image-set transfer primitive in both
directions. It still does not discover remote image IDs, list SFTP repositories,
integrate with Cockpit, operation journals, or capture/restore orchestration.
It is not yet an accepted end-user SFTP workflow. The new unit tests have not
been executed in this implementation session.
