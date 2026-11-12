# Remote image repositories

**All remote services are external to Feclora.** SSH servers, NFS exports,
SMB shares, WebDAV endpoints and S3 buckets are provisioned, operated,
patched, backed up and authorized by their
respective administrators. Feclora is only a client: it stores access
references, establishes outbound connections, mounts or transfers data,
verifies remote content and reports failures. It must not install, configure,
start, stop, administer or claim ownership of any remote server, export, share,
or peer. Feclora may stop its own client-side mount/transfer processes and release its own sessions; that is not remote-server management.

feclora keeps its image engines independent of transport by using ordinary
filesystem paths as repository roots. Provider adapters mount remote storage;
manifests, compression, encryption, checksums and restore code continue to use
the same repository API.

**Remote image distribution follows a single-publisher / multi-reader model
across SSHFS, NFS, SMB/CIFS, WebDAV and S3:** one
Client publishes each image; any number of Clients may concurrently discover,
fetch and restore that immutable published image. Concurrent remote publishers
for the same image are outside the product contract. Publication still needs
no-overwrite and incomplete-publication protections, while readers must be
able to access a committed image concurrently without modifying it.

Local disk, partition and logical-volume capture now share a pinned-directory,
manifest-last publication helper. It links immutable staged files without
replacement, fsyncs the repository after the commit marker, and on failure
removes only names that still identify the exact staged inode from that
attempt. A concurrent replacement is preserved. Readers can therefore use a
committed manifest and its immutable payload concurrently; no remote
cross-host publisher lease is implied by this local filesystem transaction.

## Provider contract

| Provider | Helper | Authentication material |
|---|---|---|
| SSH filesystem | sshfs | Dedicated SSH private key; verified host keys |
| NFS | mount.nfs, NFSv4.2 | Server/export policy |
| SMB/CIFS | mount.cifs, SMB 3.1.1 | Protected credentials file |
| WebDAV | Disabled in the repository manager | No mount is accepted until per-repository encrypted credentials and isolated davfs2 service configuration are implemented |

## Provider capability and parity matrix

This matrix describes implemented product paths, not merely installed helpers or
command builders. A provider is not complete until its Cockpit workflow,
authorization, failure handling, automated tests and operator acceptance cover
the same image lifecycle.

| Capability | SSHFS | NFS | SMB/CIFS | WebDAV | S3 |
|---|---|---|---|---|---|
| Connection / mount or transport | Integrated mount lifecycle | Integrated mount lifecycle | Integrated mount lifecycle | Disabled | Not implemented; object API required |
| Protected credentials | SSH key + pinned host keys | Export/server policy | Encrypted SMB credential | Missing isolated per-repository model | Scoped access/secret references not implemented |
| Inventory / read / restore | Via verified mounted repository | Via verified mounted repository | Via verified mounted repository | Unavailable | Not implemented |
| Capture / publish | Writable mount path exists; end-to-end provider acceptance pending | Writable mount path exists; root-squash/ownership acceptance pending | Writable mount path exists; provider acceptance pending | Blocked | Not implemented |
| Durable Cockpit lifecycle | Local operation engine for image work; mount lifecycle is separate | Same | Same | Unavailable | Not implemented |
| Byte progress / transfer resume | No provider-specific network telemetry or safe write resume acceptance | Same | Same | Unavailable | Not implemented |
| Health, interruption and recovery acceptance | Pending live server/network tests | Pending live server/network tests, including root-squash | Pending live server/network tests | Pending design | Design, API lifecycle and acceptance pending |

**Interpretation:** SSHFS, NFS and SMB share the mounted-filesystem integration
but are not yet at production acceptance parity. WebDAV remains fail-closed.
S3 is not
implemented; it requires a separate object-storage adapter rather than a
filesystem mount.

For all mounted providers, Feclora's common image engine supplies manifest
validation and artifact integrity checks; this does not replace provider-side
testing for disconnects, stale mounts, single-publisher publication
semantics, concurrent read/restore access, permissions, partial writes or
cleanup. No transport may automatically resume a destructive
write after interruption. Recovery must first establish whether the destination
is trustworthy.

The `verified` state shown by Cockpit means mount identity verification, not
a live health check. It is derived from `findmnt` metadata and the saved
provider definition. The identity query has a five-second subprocess timeout
and fails closed on timeout or malformed output; this bounds metadata
inspection only, not filesystem I/O. it must not be interpreted as proof that the remote
service is currently reachable or that reads/writes will complete. The current
manager deliberately does not issue filesystem `stat`/`statvfs` probes against
potentially hard-mounted NFS paths, because such calls can block in the kernel
when a server is unavailable. Provider-aware bounded health probes and stale
mount recovery remain unimplemented.

The provider definitions in src/feclora/storage/repository.py validate
provider inputs, reject unsafe path characters and parent traversal, and
build argument vectors without invoking a shell. Every managed SSHFS, NFS and SMB mount is requested with `nosuid,nodev,noexec`: repository data cannot provide setuid executables, device nodes or executable content to the Feclora host. These restrictive mount flags are independent of the read-only/read-write policy selected for the repository. The root-only lifecycle in
src/feclora/storage/repository_manager.py persists the currently implemented
mounted-provider definitions in a mode-0600 registry, creates private mountpoints, checks
root-owned credential references, invokes helpers without a shell, verifies
the exact mountpoint with findmnt, and checks the mounted source, filesystem
type and access mode against the saved definition. A mount action is not
reported successful merely because a mount appears at the expected path:
after the helper starts, the manager re-runs the same source/type/access-mode
verification used by repository resolution. A mismatched or unrelated
filesystem therefore fails closed and is never returned as a trusted
repository. The Cockpit **Check mount identity** action reports whether the
mountpoint is occupied by the expected provider source, filesystem type and
access mode. This is an identity/configuration check only: it does not probe
remote read/write connectivity, latency, free space, quota or service health.
A verified mount can still be stale or unable to complete I/O after a network
failure. The identity check deliberately does not issue filesystem I/O, because
a probe against a hard-mounted NFS export can block in the kernel. For an
explicit NFS unmount, Feclora first attempts a normal unmount; if that fails,
and only after acquiring the exclusive repository-use lease (so no Feclora
restore is using the mount), it retries with the kernel-supported forced NFS
unmount. SSHFS and SMB are never force-detached automatically. This is a
recovery action, not a connectivity or data-integrity health check. Cockpit
exposes add/edit/check/mount/unmount/remove and never receives credential
contents. Registry mutations (`add`, `update` and `remove`) are serialized across
processes with a separate root-owned, mode-0600 lock file opened without
following symlinks. `update` and `remove` reload the registry after acquiring that lock, so concurrent changes
to different repository IDs are not lost through stale read-modify-write
snapshots. Per-repository usage leases remain separate and continue to protect
active restore jobs. If definition removal cannot commit its registry update
after deleting the empty mountpoint, the manager recreates that mountpoint so
the still-persisted definition is not left without its local directory. 
WebDAV is currently unavailable in the repository manager. The earlier
root-invoked davfs2 integration did not provide safe per-repository credential
isolation, so Feclora now rejects WebDAV definitions rather than sharing
credentials through `/etc/davfs2/secrets`. Re-enable it only after a
per-repository encrypted credential and isolated service-configuration model
is implemented and HTTPS certificate validation is covered by tests. See the
[davfs2 configuration manual](https://manpages.debian.org/unstable/davfs2/davfs2.conf.5.en.html).

## Cockpit credential workflow

1. Prepare each source file on the Feclora host. It must be a root-owned regular
   file, mode 0600, with no symlink or hard link, between 1 byte and 1 MiB.
   This applies to `known_hosts` files too. Do not paste secret material into
   Cockpit fields or command arguments.
2. In Cockpit, open **Remote repositories → Encrypted repository credentials**.
   Enter a credential ID, select SSH private key, SSH `known_hosts` or SMB
   credentials, and enter the protected source-file path.
   Import encrypts the file locally; the browser sends only the path and receives
   only metadata. Feclora leaves the source file in place.
3. Create the repository definition and select the imported encrypted
   credential references in the provider-specific fields. SSHFS requires both
   a private key and pinned `known_hosts` entry; SMB requires an SMB file;
   NFS needs no credential.
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
credential paths for SSHFS identity keys and pinned `known_hosts` files and SMB credential
files. It launches a transient per-repository systemd service with
`LoadCredentialEncrypted=`; the mount helper reads the decrypted file only
from that service's `$CREDENTIALS_DIRECTORY`. SSHFS stays in the
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
SSH private keys, SSH `known_hosts` and SMB credentials.
The operator supplies only a path to a root-owned private source file; the API
reads it locally, encrypts it through `systemd-creds`, and returns metadata.
The source file is not deleted by Feclora. Repository definitions reference the
encrypted blob path, and the mount service receives it through
`LoadCredentialEncrypted=`. NFS does not require credentials. WebDAV remains
unavailable through the Cockpit/API path until a per-repository encrypted
credential design is implemented; the global `/etc/davfs2/secrets` file is not
used as a workaround. SFTP remains a separate transfer provider: Cockpit supports SHA-256-validated image-set publication/import, optional post-capture publication, authenticated direct disk/partition restore routing, and durable/cancellable manifest-marker inventory, import and publication. Metadata inspection remains synchronous; artifact-boundary progress is journaled, while continuous byte-level progress, resume and multi-directory discovery remain pending.
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
`identity_file` for SSHFS, or as `credential_file` for SMB repository
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
SMB credential files under
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
repository editing is available only while unmounted; the check action verifies the current mount identity but does not probe provider write access, latency or free space. WebDAV must not use `/etc/davfs2/secrets` as a Feclora multi-repository credential workaround. A safe per-repository credential model remains pending. Existing repository definitions must be updated to reference supported protected credential paths.

## Host dependencies

Install only the helper for each repository type actually used. S3
uses a separately selected maintained Fedora-compatible client and does not
require a mounted-filesystem helper.

On Fedora, install the helpers required by the providers you intend to use:

```bash
sudo dnf install fuse-sshfs nfs-utils cifs-utils davfs2
```

Only the selected provider's helper is needed. The manager checks for the
required executable before attempting a mount. Credentials are created and
provisioned separately; Feclora does not collect access keys or secret material.

## Security and durability requirements

- SSH host keys must be verified; never disable strict host-key checking.
- SSH keys, SMB credentials and WebDAV secrets must be
  stored outside image manifests and restore profiles with restrictive
  ownership and permissions. Cockpit accepts paths/aliases, never secret
  contents.
- WebDAV requires HTTPS certificate validation and per-repository protected credentials; do not use the global davfs2 secrets file for Feclora-managed repository secrets.
- NFS/SMB/SSHFS/WebDAV are storage transports, not PXE deployment
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
- A mount failure must never fall back to the local directory underneath an
  unmounted mountpoint.
- Image artifacts must be staged and the manifest published last. A remote
  backend must demonstrate the required atomicity and durability semantics
  before it can be used for production captures.

## Remaining work

Remaining engineering work: add edit/test and health/free-space workflows,
credential provisioning/rotation and recovery, safe per-repository WebDAV
credentials and live provider acceptance, plus automated coverage for every provider lifecycle. Bounded
transport retries are implemented for read-only SFTP downloads and inventory;
publication uploads remain non-retrying because their outcome can be ambiguous.
acceptance tests. SFTP file transfer is distinct from SSHFS and is not a
separate mounted filesystem provider.

## S3 object repository (planned)

S3 is a file-repository target backed by an object API, not a mounted
filesystem. The provider is not implemented in the current repository
manager. A production adapter must use TLS with certificate validation,
SigV4 or an explicitly supported compatible signing scheme, root-owned
systemd credential references, scoped bucket/prefix permissions, bounded
multipart upload/download, abort of incomplete multipart uploads, immutable
object keys and a manifest-last publication marker. It must use conditional
writes or an equivalent no-overwrite contract and distinguish object ETags
from SHA-256: ETags are not a reliable content digest for multipart objects.
Manifest authenticity must be checked against an independent trust anchor
before destructive restore. Inventory, list pagination, object versioning,
delete policy, retry semantics and lifecycle cleanup need explicit capability
and acceptance tests. S3 is not currently exposed as a usable Cockpit
repository provider or PXE restore adapter.

## NVMe over Fabrics block transport (planned)

NVMe-oF is not a file repository and does not appear in the repository
provider matrix. An NVMe-oF host connection exposes a remote namespace as a
Linux block device. Feclora may eventually provide Cockpit workflows to
discover, connect, inspect and disconnect externally provisioned NVMe
subsystems/namespaces using the Linux NVMe host stack and nvme-cli. The
remote target, subsystem, namespace, ACLs, network and fabric security are
operator-owned external infrastructure; Feclora must not configure or
administer the target.

Before a namespace is eligible for capture, restore or cloning, Feclora must
bind its stable subsystem/NQN/NSID identity to the current kernel device,
validate geometry and access mode, inspect multipath state, reject ambiguous
or duplicate paths, check mounted/in-use dependencies, and revalidate identity
immediately before destructive I/O. Disconnect must be blocked while a
namespace is in use by a Feclora operation or mounted filesystem. Transport
authentication/encryption and fabric isolation must be documented separately
from Feclora's Server-authenticated TLS control channel. No NVMe-oF host
connection manager or Cockpit workflow is implemented yet.

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
IDs. Restore reads source artifacts from the selected mount but stages age
decryption and partition decompression on the local temporary filesystem; a
read-only remote mount is therefore not used as a scratch directory. Ensure
not image capture.
