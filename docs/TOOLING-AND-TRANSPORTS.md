# Tool reuse and transport strategy

Feclora is an orchestration and safety layer. It should not reimplement mature
storage, networking, cryptography, service-management or transport software
when a maintained system tool already provides the required capability.

## Reuse policy

| Area | Preferred tool or subsystem | Feclora's responsibility |
|---|---|---|
| Filesystem-aware imaging | Partclone | Select supported filesystem engines, validate source/target, provide explicit raw fallback where appropriate, orchestrate and verify |
| Raw block I/O | Linux block devices and established system utilities | Device identity/safety checks, geometry validation, bounded I/O, confirmation and recovery state |
| Multicast artifact distribution | UDPcast | Job authorization, recipient readiness, staging, manifest/artifact verification and per-client results |
| Network configuration | NetworkManager | Use its D-Bus API, connection profiles and checkpoint/rollback facilities; do not edit network configuration behind its back |
| TLS and X.509 | OpenSSL and platform TLS libraries | CA/certificate lifecycle, validation policy, mTLS identity binding and authorization |
| Services and durable workers | systemd | Units, transient services, supervision, credentials, lifecycle and restart boundaries |
| SSH and file transfer | OpenSSH SSH/SFTP | Pinned host keys, protected key references, non-interactive transfers and Feclora-level job orchestration |
| Network filesystems | NFS utilities and mount helpers; CIFS/SMB utilities; SSHFS | Provider-specific mount lifecycle, credential isolation, mount identity verification and operation leases |
| WebDAV | davfs2 or another maintained WebDAV client | HTTPS validation and isolated per-repository credentials; never repurpose the global davfs2 secrets file as a multi-repository secret store |
| Optional peer-to-peer distribution | A maintained BitTorrent client, if selected after Fedora-baseline evaluation | Immutable artifact distribution, trusted manifest/digest verification, authorized job binding, bandwidth/peer policy and cleanup |

## Repository types and capabilities

The intended remote repository set is SSHFS, SFTP, NFS, SMB/CIFS and
WebDAV. These are distinct providers with different
capabilities; do not assume that every provider supports listing, publishing,
resuming or deleting. Feclora uses a single-publisher / multi-reader model:
one Client publishes an image and multiple Clients may read/restore that
committed image concurrently. Concurrent publishers for the same image are
not a product requirement.

- **SSHFS** is a mounted filesystem. It is not SFTP.
- **SFTP** is a file-transfer provider and must not be represented as an SSHFS
  mount. Its full inventory/progress/retry/resume lifecycle remains work in
  progress.
- **NFS and SMB/CIFS** use their native mount helpers and server-side permission
  models. Root-squash and ownership behavior must be tested.
- **WebDAV** is a required provider, but safe per-repository credential
  isolation is not complete. Do not use the global `/etc/davfs2/secrets` file
  as a shortcut.
- **BitTorrent** is an optional distribution transport, not a repository or
  general-purpose writable storage backend. It is not yet implemented. If
  added, reuse a maintained client; never implement the protocol in Feclora.

## Optional cryptographic integrations

- **age** is optional artifact encryption for confidentiality. A deployment
  without age must still be able to install and use Feclora for baseline
  imaging and deployment.
- **minisign** is an optional detached-signature implementation. A trusted
  authenticity mechanism is still required before destructive or unattended
  actions; SHA-256 alone detects corruption but does not authenticate the
  publisher.
- The baseline TLS enrollment, renewal, unicast and multicast deployment paths
  accept absent age/minisign material. The remaining minisign-specific paths are
  the SFTP signed-image-set workflow and signed unattended restore profiles;
  they are optional features, not baseline installation requirements. A
  configurable verifier or an explicitly documented SSH-host/root-owned-local
  trust policy is still needed before those features can be used without
  minisign.
- TLS/X.509 identity, mTLS peer authentication and Feclora job authorization
  are separate from optional image encryption/signing. Never substitute one
  key type or security role for another.

## Engineering rules

1. Inspect the existing implementation and the selected tool's documented
   interfaces before adding code.
2. Prefer stable command-line or D-Bus/API interfaces and argument vectors;
   never build shell command strings from user-controlled input.
3. Keep Feclora's code focused on orchestration, authorization, safety,
   capability detection, durable state, progress, diagnostics and recovery.
4. Expose provider capabilities explicitly and fail closed when a requested
   operation is unsupported.
5. Test both tool-present and tool-absent behavior for optional dependencies.
6. Pin/document supported Fedora package versions and verify that the chosen
   helper is maintained and available on the project baseline.
7. Do not advertise a feature based solely on the existence of a wrapper,
   command builder or installed executable.
