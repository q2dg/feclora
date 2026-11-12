# Configuring Server and Client deployment modes

The TLS deployment runtime is opt-in. PXE services and the control
listener do not start automatically at boot.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

See [Certificate management](CERTIFICATE-MANAGEMENT.md) for the Server CA/certificate and Client trust model.

## Filesystem preparation

Feclora creates these directories during initial Server setup. They
must remain root-owned and mode 0700. The Server creates
`/etc/feclora/deployment-server.json` automatically when it has no existing
configuration. Do not copy its CA private key to a Client.

The JSON configuration files must be root-owned regular files with mode 0600.
The CA certificate, Server certificate and Server private key must be root-owned regular files. The Server private key must have no group/other permissions. If optional image
signing/encryption is enabled, its public/private key material must be
protected with equivalent least-privilege permissions. Symlink paths are rejected.

For each Client, provision the CA certificate and configure the Server address
and expected Server certificate identity. Clients do not create, import or
present TLS certificates. The Server never authenticates individual Clients.
Do not put private keys or CA signing material in TFTP/HTTP boot assets.

## Server configuration

Install /etc/feclora/deployment-server.json with this schema (replace every
example path and identity):

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

The Server writes a private hash-chained job journal under /var/lib/feclora/deployments; the directory is created root-owned with mode 0700. On startup, verified journals reconstruct the last job/client states for operator review. This is audit-only recovery: live sessions are not recreated and destructive jobs are never resumed automatically.

For an interrupted job, the startup review offers an explicit operator reconciliation action. First inspect every Client and destination disk out of band; then select the acknowledgement and type exactly `RECONCILE <job-UUID>`. This appends a durable `operator_reconciled` event and closes the journal as failed, not successful. It does not retry, roll back, resume, or access any block device. Leaving the action pending is safe and prevents any implicit assumption about partial writes; Server refuses to create/arm another deployment until every interrupted journal has been reconciled.

Clients do not enroll or authenticate individually. The Server certificate
identity is used only by Clients to verify the Server. A selected Client MAC
is operational job selection, not an authentication credential.

The bind address must exactly match the IPv4 address selected in Server mode.
The Server UI creates either a one-client unicast save/restore job or a multi-client multicast restore job and displays the job UUID. For restore jobs, it can also collect an optional stable target binding for each selected Client (WWN, serial number, or both). When configured, the Client checks those identifiers against its current device inventory before READY; the operator still selects the local device and types the destructive confirmation. Jobs without a binding retain the ordinary interactive selection. Each selected Client operator enters that UUID. The Server listener opens TCP/9443 only on the selected interface in Feclora's temporary firewalld zone. During multicast transfers it temporarily adds the UDPcast port pair and IGMP on that same interface. The listener and temporary firewall rules are removed when the job UI exits.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Client configuration

Install /etc/feclora/deployment-client.json on each Client:

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Cockpit walkthrough and screenshots

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Illustrations may be real screenshots from a version-matched build or clearly labeled mockups. Mockups must not be presented as runtime evidence; follow the [screenshot and mockup policy](assets/screenshots/README.md).

## Scope and safety limits

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

For a multi-Client restore, the Cockpit job form can select either the local
Server image repository or a mounted, verified SSHFS/NFS/SMB repository. The
job journal stores only the managed repository ID, not a path. The Server
resolves that ID again when the persistent deployment service starts, validates
the manifest and verifies any detached signature against an independently
trusted key, then streams from that mount to each selected READY Client
(unicast) or to the complete READY receiver set (UDPcast multicast). Unsigned
images are transferred over the Server-authenticated TLS control session and each
artifact is checked against the manifest's exact size and SHA-256.
Keep the repository mounted until all Client terminal results have been
collected. The remote repository's files must satisfy Feclora's root-owned
image-manifest checks; NFS root-squash may prevent this.

## PXE Live and unattended answer workflow

The embedded PXE stack boots the same Fedora Live kernel, initramfs and
squashfs used by the Feclora ISO. The interactive PXE entry opens the normal
Live Cockpit interface; operators do not need to boot the ISO manually.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

### Destructive-operation security boundary

The answer JSON is declarative data, not shell code. It identifies the image,
repository and stable whole-disk WWN/serial selector and explicitly requests
restore/start. The Server validates it before publication. The Live image downloads and validates the answer. NFS or credential-free HTTPS object repository access,
unique target resolution and immediate pre-write identity revalidation are
connected for whole-disk restore. Other repository providers and physical
acceptance remain pending. A URL, DHCP lease, MAC address, job UUID or successful
download is not authorization by itself.

The current implementation downloads and validates the answer in Live and
connects NFS- or credential-free HTTPS-backed whole-disk restore to the existing engine. The target is
revalidated immediately before writing and the result is read back. Other
repository schemes and hardware acceptance remain pending; test only with
disposable disks. The PXE Server enforces the configured unique-MAC count
and/or serving-time limit, but MAC spoofing is not prevented and MAC is not an
authentication mechanism.

### Durable Client progress and restart history

The Server journals bounded progress checkpoints received over the Server-authenticated TLS session. The first snapshot for a Client is persisted, followed by checkpoints after at least 1 MiB of additional progress or five seconds; phase and total-size changes are also persisted immediately. This bounds journal growth while retaining useful restart diagnostics. The Deployment history view reports the last durable checkpoint per Client, not a live rate estimate.

A progress checkpoint is an audit record, not a recovery cursor. After a Server process or host restart, Feclora does not reconnect the old Client session, continue a transfer, or resume disk I/O. The last recorded byte count may precede the actual point of interruption. Operators must inspect every Client and destination device and reconcile the interrupted job before creating a new one. A partially written destination remains potentially unusable.
