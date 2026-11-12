# Tool reuse and transport strategy

Feclora is an orchestration and safety layer. It should reuse maintained
storage, networking, cryptography, service-management and transport software.

## Reuse policy

| Area | Preferred tool or subsystem | Feclora's responsibility |
|---|---|---|
| Filesystem-aware imaging | Partclone | Select supported filesystem engines, validate source/target, provide explicit raw fallback, orchestrate and verify |
| Raw block I/O | Linux block devices and established system utilities | Device identity/safety checks, geometry validation, bounded I/O, confirmation and recovery state |
| Multicast artifact distribution | UDPcast | Job authorization, recipient readiness, staging, manifest/artifact verification and per-client results |
| Network configuration | NetworkManager | D-Bus profiles and checkpoint/rollback; do not edit configuration behind its back |
| TLS and X.509 | OpenSSL and platform TLS libraries | CA/Server-certificate lifecycle and Client-side Server-certificate validation |
| Services and durable workers | systemd | Units, transient services, supervision, credentials, lifecycle and restart boundaries |
| SSH and file transfer | OpenSSH SSH/SFTP | Pinned host keys, protected key references, non-interactive transfers and job orchestration |
| Network filesystems | NFS utilities, CIFS/SMB utilities and SSHFS | Provider-specific mount lifecycle, credential isolation, mount identity and operation leases |
| WebDAV | davfs2 or another maintained WebDAV client | HTTPS validation and isolated per-repository credentials; never use the global davfs2 secrets file as a multi-repository secret store |
| S3 object storage | AWS SDK/CLI with SigV4 support | Object-key mapping, multipart upload/download, manifest-last publication, conditional no-overwrite semantics, integrity and credential isolation |
| NVMe over Fabrics | Linux kernel NVMe host and nvme-cli | Discover/connect/disconnect externally provisioned namespaces, validate subsystem/NQN/NSID identity, expose safe block devices to existing storage engines |

## Storage and transport taxonomy

These technologies are not interchangeable:

- **SSHFS, NFS and SMB/CIFS** are mounted filesystem repositories.
- **SFTP** is a file-transfer provider, not an SSHFS mount.
- **WebDAV** is a filesystem-style repository; isolated credentials and
  HTTPS validation are required before it can be enabled.
- **S3** is object storage. It must use an object API, not pretend to be a
  POSIX mount. Publication needs multipart lifecycle handling, abort/cleanup,
  immutable object keys, conditional manifest commit, and independent
  manifest authenticity plus artifact digest verification.
- **NVMe-oF** is a remote block-device transport. A connected namespace appears
  as a Linux block device and can be selected as an image source or target
  after the normal topology, mounted/in-use, capacity and identity checks.
  Feclora is an NVMe host/client; it must not configure or administer the
  remote NVMe target/subsystem.

S3 and NVMe-oF are planned integrations, not currently supported Cockpit
providers. Do not infer support from a URL scheme, installed package, command
builder or connected kernel device alone. The current unattended PXE execution
path is NFS-only.

## Repository model

The intended file-repository set is SSHFS, SFTP, NFS, SMB/CIFS, WebDAV and S3.
They have different capabilities; do not assume every provider supports
listing, publishing, conditional writes, resume or deletion. The distribution
model is single-publisher / multi-reader: one Client publishes an image set,
while multiple Clients may concurrently read and restore committed images.
Concurrent publishers for the same image are out of scope.

NVMe-oF is deliberately outside this repository list. It exposes a block
namespace, not an image-set catalog. Its lifecycle and safety checks belong in
a separate block-device transport workflow.

## Optional cryptographic integrations

- **age** is optional artifact encryption for confidentiality. A deployment
  without age must still be able to use baseline imaging and deployment.
- **minisign** is an optional detached-signature implementation. A trusted
  authenticity mechanism is still required before destructive or unattended
  actions; SHA-256 alone detects corruption but does not authenticate a
  publisher.
- Server-authenticated TLS, unicast and multicast deployment accept absent
  age/minisign material. SFTP signed-image workflows currently have minisign
  implementation dependencies; a configurable verifier is still required
  before that integration can be made optional in practice.
- S3 must use encrypted transport, scoped credentials and a separately
  configured trust anchor for manifests. Object ETags are not a substitute
  for SHA-256 or publisher authentication.
- NVMe-oF transport security depends on the selected fabric and host/target
  configuration. TLS on Feclora's deployment control channel does not secure
  an independently connected NVMe-oF data path.

## Engineering rules

1. Inspect the existing implementation and selected tool's documented
   interfaces before adding code.
2. Prefer stable command-line or D-Bus/API interfaces and argument vectors;
   never build shell command strings from user-controlled input.
3. Keep Feclora focused on orchestration, authorization, safety, capability
   detection, durable state, progress, diagnostics and recovery.
4. Expose provider capabilities explicitly and fail closed when unsupported.
5. Test both tool-present and tool-absent behavior for optional dependencies.
6. Pin/document supported Fedora package versions and verify helper
   availability on the project baseline.
7. Never advertise a feature solely because a wrapper, command builder,
   URL parser or kernel device exists.
