# Remote image repositories

Feclora stores image artifacts and manifests in an explicitly selected
repository. Remote storage services are provisioned, operated and backed up by
their administrators; Feclora implements only the client-side connection,
credentials, transfer, integrity and failure handling.

## Supported filesystem repositories

SSHFS, NFS and SMB/CIFS are implemented as mounted filesystem providers.
Their lifecycle is managed by the Server and exposed through Cockpit.

| Provider | Client mechanism | Authentication |
|---|---|---|
| SSHFS | `sshfs` | Dedicated SSH key and pinned host keys |
| NFS | `mount.nfs`, NFSv4.2 | Server export policy |
| SMB/CIFS | `mount.cifs`, SMB 3.1.1 | Protected credentials file |

All managed mounts request `nosuid,nodev,noexec`. The manager verifies the
mounted source, filesystem type and access mode before returning a repository
to image operations. A verified mount identity is not a live connectivity or
read/write health check.

Cockpit image inventory holds a shared repository usage lease for the entire manifest scan. The lease prevents unmount, definition changes or removal from racing with the scan; it is released on both success and failure. S3 inventory similarly holds its object-repository usage lease while listing committed image sets. Inventory is a real remote read operation, not a connectivity probe, and may still fail or block according to the remote provider's behavior.

The image engine publishes immutable artifacts and a manifest commit marker.
Local publication uses no-overwrite links and publishes the manifest last.
Remote provider acceptance must additionally cover disconnects, stale mounts,
permissions, partial writes, concurrent readers and cleanup. The supported
distribution model is one publisher per image and multiple concurrent readers.

## S3-compatible object repositories

S3 is an object-store integration, not a filesystem mount. The object adapter, separate root-managed repository registry, encrypted credentials, API and Cockpit configuration are implemented. Local capture, inventory, verified download, inspection, verification, extraction and restore use private temporary staging; the adapter uses
the S3 HTTPS API directly and will not require FUSE. The same provider
configuration is intended to work with AWS S3, Cloudflare R2, Garage and
other services implementing the required S3 API operations.

Each repository consists of an endpoint URL, region, bucket, optional key
prefix and a dedicated access-key pair. Access is scoped to the bucket/prefix;
credentials are stored using the host's encrypted credential mechanism and
are never returned to Cockpit.

The object layout preserves the image engine's manifest model:

- Each artifact is uploaded to a unique immutable object key.
- Uploads use bounded multipart transfer for large artifacts.
- Feclora verifies object size and SHA-256 before committing an image.
- Failed multipart uploads are aborted where supported.
- The manifest is uploaded last and is the visibility/commit marker for the
  complete image set.
- Inventory lists only valid committed manifests; orphaned staging objects
  are not treated as images.
- Restore downloads and verifies every referenced artifact before writing to
  a block device. Destructive restore never resumes automatically after an
  interrupted transfer.

The object adapter must use conditional no-overwrite operations where the
provider supports them. Provider compatibility tests must verify the required
conditional-write and multipart semantics; an endpoint is not considered
supported merely because it accepts basic S3 uploads.

### Distributed deployment jobs

The persistent Cockpit deployment service can use an S3 repository for both
unicast/multicast restore sources and unicast Client capture destinations.
For restore, the Server acquires a repository usage lease, downloads the
committed image into a private temporary directory, verifies every artifact,
and only then makes it available to the deployment transfer engine. The
existing Server-authenticated TLS control/data channel delivers the image to
Clients; no S3 endpoint, access key or secret is sent to a Client.

For Client capture, the Server receives the complete image set over the
authenticated TLS channel into private local staging. It verifies the
manifest, sizes and SHA-256 digests, then uploads the artifacts and publishes
the S3 manifest last. The job is not reported successful if S3 publication
fails. Temporary staging is removed when the service exits. Repository
update/removal is blocked while a deployment holds its usage lease.

The Cockpit deployment form allows S3 selection as a restore source or as a
writable Client-capture destination. A read-only S3 definition may be used
only as a restore source. The current network capture path remains whole-disk
and unicast; the existing restore transports retain their own target and
multicast constraints.

### Live endpoint acceptance

An opt-in integration test exercises conditional object creation, manifest
commit, inventory, download and SHA-256 verification against a real
S3-compatible endpoint. Configure these environment variables on a trusted
test host (never commit them):

- `FECLORA_S3_TEST_ENDPOINT` — HTTPS endpoint URL.
- `FECLORA_S3_TEST_REGION` — signing region (Garage commonly uses its configured region; R2 uses `auto`).
- `FECLORA_S3_TEST_BUCKET` — pre-created test bucket.
- `FECLORA_S3_TEST_ACCESS_KEY_ID` and `FECLORA_S3_TEST_SECRET_ACCESS_KEY` — scoped test credentials.
- `FECLORA_S3_TEST_PREFIX` — optional dedicated prefix for the probe.

Run `python3 -m unittest tests.test_s3_live_compatibility -v`. The test
creates a uniquely named test image below
`feclora-compatibility-tests/` and deletes its objects in a `finally` block.
The credential policy needs list, get, put and delete rights only within that
test bucket/prefix. Run the test independently against each intended provider;
a successful AWS test does not establish Garage or R2 compatibility.

### Self-hosted and managed endpoints

For a self-hosted endpoint, Garage is a lightweight S3-compatible server
suitable for small and medium deployments. It can be exposed through Caddy or
Nginx with HTTPS, so the public-facing setup remains similar to a simple
HTTPS file service while Feclora uses authenticated object operations.

Managed S3-compatible services such as Cloudflare R2 avoid operating the
storage server. In either case, the endpoint and bucket remain external to
Feclora.

## Credentials

Repository definitions contain credential references, never secret values.
Imported credential files must be root-owned, regular, private files with no
symlink or hard link. Encrypted credentials are host-bound and must be
reprovisioned when moving to another Server or recovering after loss of the
host credential key.

SSHFS requires a private key and pinned host keys; SMB requires a protected
credentials file; NFS uses server-side export policy. S3 requires a dedicated
access key ID and secret access key with least-privilege bucket/prefix
permissions.

## Operational boundary

Feclora does not create buckets, configure remote permissions, manage TLS
certificates on remote hosts, or administer storage servers. The operator
must provision the endpoint, bucket/export/share, access policy, network
reachability and backups before adding the repository in Cockpit.
