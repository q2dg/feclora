# Remote image repositories

**All remote services are external to Feclora.** SSH/SFTP servers, NFS exports,
SMB shares, WebDAV endpoints, BitTorrent trackers
and peers are provisioned, operated, patched, backed up and authorized by their
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
across SSHFS, SFTP, NFS, SMB/CIFS, WebDAV and BitTorrent:** one
Client publishes each image; any number of Clients may concurrently discover,
fetch and restore that immutable published image. Concurrent remote publishers
for the same image are outside the product contract. Publication still needs
no-overwrite and incomplete-publication protections, while readers must be
able to access a committed image concurrently without modifying it.

## Provider contract

SFTP is intentionally not represented as a mounted filesystem provider. Feclora now exposes one-shot image-set import and publication actions in Cockpit, using pinned host keys and encrypted systemd credential references. The current implementation uses minisign-authenticated manifests for these actions; this is a current implementation dependency, not a product-wide requirement. The target is a configurable verifier so minisign remains optional. The workflow transfers an already captured, authenticated local image to an existing SFTP directory, or fetches and verifies a remote image into the local repository. Named endpoint definitions, one-directory inventory that exposes only manifests with their detached signature present, signed metadata inspection and direct disk/partition restore routing are integrated. Publication uploads artifacts first, then the detached signature, and the manifest last as the visibility marker. Byte-level progress, operator cancellation, resume, multi-directory discovery and full provider acceptance remain pending. Bounded retries are limited to transient download/inventory failures; uploads are not automatically retried because publication outcomes can be ambiguous. SSHFS mounts do not satisfy the SFTP transfer contract.

| Provider | Helper | Authentication material |
|---|---|---|
| SSH filesystem | sshfs | Dedicated SSH private key; verified host keys |
| SFTP | OpenSSH SFTP batch adapter; signed image-set import and publication from Cockpit | Registered encrypted SSH key and known_hosts references loaded by transient systemd credentials; one-shot local-repository transfer actions |
| NFS | mount.nfs, NFSv4.2 | Server/export policy |
| SMB/CIFS | mount.cifs, SMB 3.1.1 | Protected credentials file |
| WebDAV | Disabled in the repository manager | No mount is accepted until per-repository encrypted credentials and isolated davfs2 service configuration are implemented |

## Provider capability and parity matrix

This matrix describes implemented product paths, not merely installed helpers or
command builders. A provider is not complete until its Cockpit workflow,
authorization, failure handling, automated tests and operator acceptance cover
the same image lifecycle.

| Capability | SSHFS | NFS | SMB/CIFS | WebDAV | SFTP | BitTorrent |
|---|---|---|---|---|---|---|
| Connection / mount or transport | Integrated mount lifecycle | Integrated mount lifecycle | Integrated mount lifecycle | Disabled | OpenSSH batch transfer | Not implemented |
| Protected credentials | SSH key + pinned host keys | Export/server policy | Encrypted SMB credential | Missing isolated per-repository model | Encrypted SSH key + pinned host keys | Not applicable yet |
| Inventory / read / restore | Via verified mounted repository | Via verified mounted repository | Via verified mounted repository | Unavailable | Signed manifest inventory and authenticated fetch/restore | Not implemented |
| Capture / publish | Writable mount path exists; end-to-end provider acceptance pending | Writable mount path exists; root-squash/ownership acceptance pending | Writable mount path exists; provider acceptance pending | Blocked | Signed no-overwrite image-set publication exists; synchronous and not yet fully durable | Immutable distribution only, not publication |
| Durable Cockpit lifecycle | Local operation engine for image work; mount lifecycle is separate | Same | Same | Unavailable | Inventory durable/cancellable; metadata inspection, import and publication still synchronous | Not implemented |
| Byte progress / transfer resume | No provider-specific network telemetry or safe write resume acceptance | Same | Same | Unavailable | Byte progress and resume pending | Not implemented |
| Health, interruption and recovery acceptance | Pending live server/network tests | Pending live server/network tests, including root-squash | Pending live server/network tests | Pending design | Multi-directory discovery, health checks and live acceptance pending | Design and implementation pending |

**Interpretation:** SSHFS, NFS and SMB share the mounted-filesystem integration
but are not yet at production acceptance parity. WebDAV remains fail-closed.
SFTP has richer signed file-transfer workflows than the mounted providers in
some areas, but still lacks durable byte-level transfer controls. BitTorrent is
a separate optional immutable-artifact distribution feature, not a repository
mount or writable publication backend.

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
build argument vectors without invoking a shell. The root-only lifecycle in
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
failure. Cockpit exposes add/edit/check/mount/unmount/remove and never receives
credential contents. Registry mutations (`add`, `update` and `remove`) are serialized across
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
used as a workaround. SFTP remains a separate transfer provider: Cockpit supports signed image-set publication/import, optional post-capture publication, authenticated direct disk/partition restore routing, and durable/cancellable manifest-marker inventory. Metadata inspection and artifact import/publication remain synchronous; byte-level transfer progress, resume and multi-directory discovery remain pending.
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

Install only the helper for each repository type actually used. BitTorrent is
not currently an implemented dependency; any future integration must remain
optional and use a maintained Fedora-compatible client.

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
credentials, SFTP operator cancellation, resume, multi-directory discovery
and live provider acceptance, plus automated coverage for every provider lifecycle. Bounded
transport retries are implemented for read-only SFTP downloads and inventory;
publication uploads remain non-retrying because their outcome can be ambiguous.
acceptance tests. SFTP file transfer is distinct from SSHFS and is not a
separate mounted filesystem provider.

## BitTorrent artifact distribution

BitTorrent is a first-class peer-to-peer distribution transport, at the same priority as the other remote transports, for immutable
image artifacts, not a writable repository and not a substitute for the
repository metadata/credential lifecycle. If integrated, Feclora must reuse a
maintained client rather than implement the protocol. Torrent metadata and
peer availability are untrusted transport data: before restore, verify the
manifest through the configured independent trust mechanism, verify every
artifact's exact size and SHA-256, and bind the manifest digest to the
job/profile authorization. Implement cancellation, incomplete-download
cleanup, peer/network restrictions, bandwidth limits and an explicit seeding
policy. BitTorrent remains a distribution transport rather than a writable
repository; its maintained client is selected independently and is not a
prerequisite for local-only Feclora operation.


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

The adapter has a companion runner, `sftp_transfer_service.py`, which resolves registered `ssh-key` and `known-hosts` encrypted credential references and executes transfers in synchronous transient systemd services using `LoadCredentialEncrypted=`. Plaintext credentials exist only in the service's private `CREDENTIALS_DIRECTORY`; the API-side invocation contains only encrypted blob paths and non-secret transfer parameters. Cockpit exposes one-shot signed-image inventory/inspection, import and publication actions; named SFTP endpoints can be saved, and SFTP fetch is integrated with durable disk/partition restore jobs. Optional post-capture publication is also supported.

This is still not a complete SFTP repository provider. OpenSSH SFTP does not provide a portable server-side SHA-256 operation, so upload returns the locally computed digest and relies on signed-manifest verification when the artifact is consumed. Transfers remain synchronous: there is no byte-level progress, operator cancellation or resume protocol. Transient connection failures during read-only downloads and inventory are retried up to twice with a fresh transient unit; uploads are never automatically retried because a lost response can leave publication outcome ambiguous. Multi-directory catalog discovery is also pending. A failed multi-file publication can leave unreferenced remote files; final names are no-overwrite, so an operator may need to remove those orphaned files before retrying. Unit tests exist, but live provider acceptance remains outstanding. Do not select SSHFS when SFTP file-transfer semantics are required.


### Signed SFTP image-set publication primitive

`sftp_image_set.py` adds a standalone publisher for the existing manifest v1
format. Before any network transfer it parses the manifest, verifies the
detached minisign signature against a separately supplied trusted public key,
and checks every local artifact's regular-file type, byte count and SHA-256
against the signed manifest. It uploads each artifact, then the detached
`manifest.json.minisig`, and publishes `manifest.json` last. The manifest is
the visibility/commit marker: inventory requires both files, so concurrent
readers cannot discover the set in the interval between metadata uploads. A
consumer must still verify the detached signature and independently check
every artifact before import or restore.

Each individual upload retains the adapter's random staging name and uses the
OpenSSH hard-link extension for atomic no-overwrite publication; servers that
do not support that extension fail closed. Artifact filenames are also barred
from the native local repository's manifest-marker namespace
(`manifest.json`, `manifest.json.minisig`, and
`<image_id>.manifest.json[.minisig]`) so an artifact cannot collide with
another image's discovery metadata during import. This is not a multi-file atomic transaction:
failed publication can leave unreferenced remote artifacts or a detached
signature without its manifest. Such a set remains invisible to inventory and
must be rejected. The
publisher does not yet implement remote inventory/garbage collection,
download-side manifest discovery, operation-journal progress, Cockpit actions,
or capture/restore routing. It is an integration primitive, not end-user SFTP
support; SFTP remains outside the complete provider acceptance gate.


The same module now includes `fetch_image_set()`. It downloads only
`manifest.json` and `manifest.json.minisig` in explicitly marked unverified
metadata mode into a new private staging directory. It enforces metadata size
limits, parses the existing manifest schema and verifies minisign against an
independently trusted public key before requesting any image artifact.
Artifacts are downloaded with their signed SHA-256 values and checked
again for byte count and digest. The verified set is then imported into the
native Feclora repository layout: artifact files, followed by
`<image_id>.manifest.json.minisig`, followed by
`<image_id>.manifest.json` as the final commit marker expected by the
existing Cockpit inventory and restore code. Each file is published with a
no-overwrite hard link. If any destination already exists, import fails
without replacing it and removes files created earlier in that attempt.
This is a manifest-last multi-file publication, not a single atomic directory
transaction; readers must treat the manifest as the visibility/commit marker.
Failed or invalid retrievals remove the private staging directory.

The metadata download mode is restricted by the transient-service CLI to the
two metadata filenames; it never marks them as verified. Artifact download
results explicitly report digest verification. The destination root must
already exist and must not contain symlinked path components. The remote
directory must already exist on the SFTP server.

Cockpit now exposes a one-shot **Fetch, verify and import image** form. The
operator selects an encrypted SSH private-key reference and a pinned
`known_hosts` reference; the API resolves those references through the
systemd credential inventory and runs the transfer in a transient service.
The import uses the local `/etc/feclora/pki/server.pub` as its independent
minisign trust anchor and writes into the native local image repository. The
operation is recorded in the local operation journal. No plaintext SSH
material is sent through Cockpit.

The SFTP Cockpit workflow now supports one-shot import and publication of existing signed images, optional post-capture publication, remote manifest-marker listing, and **Verify signed remote image metadata**. The current implementation downloads `manifest.json` and its detached signature into a private temporary directory and verifies it against the independent local Feclora minisign trust key. This is a current SFTP implementation limitation; minisign must remain optional at the product level and the transfer verifier needs a configurable alternative. It does not download artifact bytes; artifact SHA-256/size verification still occurs during import. Inventory is submitted from Cockpit as a durable local operation and runs in the root-owned local-operation worker; its SFTP child transfer uses a transient systemd service with encrypted SSH-key and pinned `known_hosts` credentials. Its queued/running/terminal state is visible in Operation log and can be cancelled through the existing worker cancellation path. Inventory currently reports completion as a whole operation rather than byte-level progress. Metadata inspection remains a synchronous request.

The Restore wizard can now use the authenticated remote image directly: after metadata inspection, the operator selects **Fetch and verify the authenticated SFTP image before restoring it**. Current SFTP manifest authentication is minisign-backed; the optional-minisign policy is not yet fully implemented in this code path. The durable restore definition stores only the remote endpoint and encrypted credential references. Before destructive restore starts, the worker fetches the signed image set into the protected local repository, requires both the fetched manifest image ID and SHA-256 to match the authenticated metadata preview, verifies the signature before artifact retrieval, and verifies each artifact's size and SHA-256 before import. The normal restore path then revalidates the local manifest and performs the existing target confirmation and restore checks. A failed fetch does not start the destructive restore; a successfully imported image remains local if the subsequent restore fails. Cockpit can save and reuse named SFTP connection definitions in the private root-owned `/etc/feclora/sftp-repositories.json` registry; it stores only endpoint metadata and encrypted SSH-key/known_hosts references. The workflow still lacks multi-directory discovery, durable byte-level transfer progress, resume and end-to-end provider acceptance. Inventory is durable/cancellable; metadata inspection and the separate import/publication actions remain synchronous. The synchronous transfer actions do not expose transfer progress in Cockpit. Bounded retry is restricted to transient read/inventory transport faults; uploads are deliberately not retried automatically. Unit tests have been added but have not been executed in this session.


### Automatic SFTP publication after capture

The disk and partition capture forms also provide an optional **SFTP post-capture publication** setting. When enabled, the capture definition stores only the host, remote directory and encrypted credential references in the root-owned durable operation record. The capture must be signed; unsigned capture plus SFTP publication is rejected during job validation. After the native capture completes, the worker verifies the newly written manifest signature and each artifact digest, then publishes the set through the same no-overwrite SFTP image-set publisher. The capture job is reported failed if publication fails, but the successfully captured local image remains in the repository and can be published manually or retried after the remote conflict/connectivity issue is resolved. SFTP upload still has no byte-level progress, cancellation, resume or automatic retry. Upload retries remain operator-controlled because a lost response may follow successful no-overwrite publication.

### Cockpit SFTP publication and import

The Remote Repositories tab exposes two explicit operations:

- **Publish a signed image set** selects an already captured, locally stored and signed image. The API chooses the local Server minisign keypair, or the enrolled Client's local signing keypair, validates ownership and permissions, verifies the detached signature and every artifact against the manifest, then uploads the artifacts, detached signature and manifest last using encrypted SSH-key and pinned `known_hosts` credentials. The manifest is the inventory visibility marker.
- **Import a signed image set** fetches the manifest and detached signature first, verifies them against the trusted Feclora signing public key, then downloads and verifies each artifact before importing the files into the local repository.

The destination directory must already exist. Remote files are never overwritten. A failed publication can leave unreferenced remote artifacts; because overwrite is refused, an operator may need to remove those orphaned files before retrying. These are synchronous one-shot actions: there is no byte-level progress, operator cancellation or resume policy. Transient read-only download/inventory failures receive bounded retries; publication is not automatically retried. Saved SFTP connection definitions are available, but multi-directory remote inventory discovery remains pending. Publication is limited to images signed by the local signing identity selected by the API; a different signer is rejected by signature verification.
