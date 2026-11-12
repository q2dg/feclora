# Tooling and transports

Feclora reuses established Linux utilities and libraries rather than
reimplementing storage and network protocols.

## Repository providers

| Provider | Mechanism | Notes |
|---|---|---|
| SSHFS | `sshfs` | Host-key verification and protected SSH credentials |
| NFS | `mount.nfs` | NFSv4.2; server-side export permissions remain external |
| SMB/CIFS | `mount.cifs` | SMB 3.1.1, signing/encryption and protected credentials |
| S3 | S3-compatible object API | SigV4, scoped credentials, multipart transfer and manifest-last publication; not a filesystem mount |

Initial S3 transfer primitives use an object-store adapter, not a FUSE mount. The full repository-manager, encrypted-credential, API and Cockpit workflow remains in progress.
Self-hosted Garage and managed S3-compatible services can expose the same API.
The endpoint, bucket and prefix are configured per repository.

## Design constraints

- Remote services are provisioned and administered by their owners.
- Secrets are never accepted inline in repository definitions or returned by
  the management API.
- File-system mounts use restrictive `nosuid,nodev,noexec` options and
  verify the mounted source before image operations.
- Object storage uses immutable artifact keys, verifies SHA-256 and byte
  counts, aborts failed multipart uploads, and publishes the manifest last.
- TLS certificate validation remains enabled for HTTPS endpoints.
- Repository operations must preserve cancellation, progress reporting and
  failure visibility.

## Existing system tools

| Function | Existing tool |
|---|---|
| SSH file access | `sshfs`, OpenSSH |
| NFS access | `mount.nfs` |
| SMB access | `mount.cifs` |
| Encrypted service credentials | `systemd-creds`, `systemd-run` |
| S3 object API | AWS SDK for Python (SigV4) |
| TLS reverse proxy for self-hosted endpoints | Caddy |

The Cockpit interface manages Feclora's client-side repository configuration;
it does not deploy or administer the remote storage service.
