# Configuring Server and Client deployment modes

The TLS deployment runtime is opt-in. PXE services and the control
listener do not start automatically at boot.

**Live-session lifetime:** the default Live root is ephemeral. Server/Client
configuration, managed CA and Server private keys,
repository definitions/credentials, deployment journals and local operation
history stored under `/etc` or `/var/lib` are session-local and disappear on
reboot. Reboot starts a new Feclora session; reconfigure as required. This is intentional and no Live persistence disk is selected
implicitly. If power is lost during a destructive operation, assume the target
may be partially written and inspect it before reuse; the previous session's
journal may no longer exist. On first Server use, Feclora
creates a root-only local CA and Server TLS identity, then generates a default
Server configuration. Optional age/minisign keys may be provisioned when the
corresponding executables are installed, but their use is selected per image.
Clients do not have TLS certificates or private keys. They validate the Server certificate using the configured CA and Server identity. Age identities and minisign signing keys are optional image-security features. Missing image-security tools never block ordinary deployment over Server-authenticated TLS.
External organizational PKI remains supported.

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

~~~json
{
  "schema_version": 1,
  "bind_address": "192.0.2.2",
  "port": 9443,
  "local_identity": "URI:feclora-server",
  "ca_file": "/etc/feclora/pki/ca.crt",
  "certificate_file": "/etc/feclora/pki/server.crt",
  "private_key_file": "/etc/feclora/pki/server.key",
  "client_minisign_public_keys": {
    "52:54:00:12:34:56": "/etc/feclora/pki/client-01.pub",
    "52:54:00:12:34:57": "/etc/feclora/pki/client-02.pub"
  },
  "server_minisign_public_key": "/etc/feclora/pki/server.pub",
  "repository": "/var/lib/feclora/images"
}
~~~

The `client_minisign_public_keys` map and `server_minisign_public_key` field
are optional. Omit them or use an empty map when image signing is not used.
Client runtime configuration may likewise leave `trusted_server_public_key`,
`local_minisign_secret_key`, `local_minisign_public_key`, `age_identity_file`
and `age_recipients_file` unset. The Server CA file, Server certificate and Server private key remain mandatory.

The Server writes a private hash-chained job journal under /var/lib/feclora/deployments; the directory is created root-owned with mode 0700. On startup, verified journals reconstruct the last job/client states for operator review. This is audit-only recovery: live sessions are not recreated and destructive jobs are never resumed automatically.

For an interrupted job, the startup review offers an explicit operator reconciliation action. First inspect every Client and destination disk out of band; then select the acknowledgement and type exactly `RECONCILE <job-UUID>`. This appends a durable `operator_reconciled` event and closes the journal as failed, not successful. It does not retry, roll back, resume, or access any block device. Leaving the action pending is safe and prevents any implicit assumption about partial writes; Server refuses to create/arm another deployment until every interrupted journal has been reconciled.

Clients do not enroll or authenticate individually. The Server certificate
identity is used only by Clients to verify the Server. A selected Client MAC
is operational job selection, not an authentication credential.

The bind address must exactly match the IPv4 address selected in Server mode.
The Server UI creates either a one-client unicast save/restore job or a multi-client multicast restore job and displays the job UUID. For restore jobs, it can also collect an optional stable target binding for each selected Client (WWN, serial number, or both). When configured, the Client checks those identifiers against its current device inventory before READY; the operator still selects the local device and types the destructive confirmation. Jobs without a binding retain the ordinary interactive selection. Each selected Client operator enters that UUID. The Server listener opens TCP/9443 only on the selected interface in Feclora's temporary firewalld zone. During multicast transfers it temporarily adds the UDPcast port pair and IGMP on that same interface. The listener and temporary firewall rules are removed when the job UI exits.

For restore/save, Feclora verifies artifact hashes and any configured detached
signature against independently provisioned trust. `minisign` is an optional
implementation, not a mandatory deployment dependency. Where no signature is
configured, SHA-256 alone is not proof of publisher authenticity; destructive
or unattended jobs must bind the manifest digest to a separately trusted
job/profile authorization.

## Client configuration

Install /etc/feclora/deployment-client.json on each Client:

~~~json
{
  "schema_version": 1,
  "host": "192.0.2.2",
  "port": 9443,
    "server_identity": "URI:feclora-server",
  "mac_address": "52:54:00:12:34:56",
  "ca_file": "/etc/feclora/pki/ca.crt",
  "trusted_server_public_key": "/etc/feclora/pki/server.pub",
  "local_minisign_secret_key": "/etc/feclora/pki/client-01.key.minisign",
  "local_minisign_public_key": "/etc/feclora/pki/client-01.pub",
  "age_identity_file": "/etc/feclora/pki/client-01.age",
  "age_recipients_file": "/etc/feclora/pki/age-recipients.txt",
  "repository": "/var/lib/feclora/images"
}
~~~

The example above is configured for a Client that has the capability to create signed and age-encrypted images. A Client may omit either capability independently. A restore-only Client should set `local_minisign_secret_key` and `local_minisign_public_key` to `null` unless it also needs to verify images signed by that Client. Key presence makes an option available; it does not enable that protection automatically. Each remote save asks the operator to choose age encryption and minisign signing for that image.

Select Client mode, enter the job UUID shown by Server, select the local
whole disk or existing target partition as specified by the job, and type the exact operation-specific confirmation. For restore,
the phrase is ERASE /dev/DEVICE. For save, it is READ /dev/DEVICE. The /dev path and confirmation remain
local; only a human-readable disk description is sent to Server. The Client
must independently approve the target before sending READY. For a remote
save job, the Client Cockpit form asks whether this image should use age
encryption and/or a minisign signature. Both choices default off and are
validated against locally enrolled keys and installed executables; they apply
only to that capture.

## Cockpit walkthrough and screenshots

The Server and Client Cockpit procedures are described above in operational
order: configure Server trust on each Client, create a Server job, inspect it from each Client,
approve each local target, wait for READY, and explicitly ARM the job on the
Server. For a save job, the Client chooses compression and per-image age
encryption/minisign signing before the local read begins.

Illustrations may be real screenshots from a version-matched build or clearly labeled mockups. Mockups must not be presented as runtime evidence; follow the [screenshot and mockup policy](assets/screenshots/README.md).

## Scope and safety limits

- Unicast supports one selected Client per job: whole-disk save, and whole-disk or existing-partition restore.
- Multicast supports one-to-many **restore** of whole-disk or partition images to existing local targets on multiple selected Clients. The Server-authenticated TLS control plane obtains local target approval, distributes the manifest and any optional detached signature, and records per-client results. Clients do not authenticate individually. Each Client stages privately, verifies any present signature and the exact artifact size/SHA-256 before invoking the normal protected restore/read-back path. Partition targets are not created or resized.
- Multicast uses an administratively scoped 239.0.0.0/8 data group, a derived separate rendezvous group, an even UDPcast port base (the base and base+1 UDP ports plus IGMP are opened temporarily), TTL 1 and a 100 Mbit/s default sender limit. Each Client selects its own local receive interface; it need not have the same interface name as the Server.
- Multicast requires all selected Clients on the same multicast-enabled L2/VLAN segment, with switch IGMP snooping and a functioning querier. The current TTL=1 profile does not support routed cross-VLAN multicast. Use unicast when the network cannot meet these conditions.
- Multicast jobs verify the manifest and artifact digests and enforce the configured authenticity policy. Optional age encryption protects confidentiality for configured recipients; optional minisign signatures authenticate manifests when enabled. Neither age nor minisign is a mandatory dependency. If neither is used, the job must still receive an independently authenticated manifest/digest bound to the authorized deployment. This is artifact-level protection, not per-datagram authentication: UDPcast metadata remains visible and an on-path attacker can still disrupt a transfer. The Server and Client perform local interface/route/tool preflight; switch IGMP snooping and querier configuration must still be verified by the operator.
- Multicast save, partition-image capture over the network, multi-client unicast, unattended target approval, automatic restart/resume of destructive writes, per-client live byte progress, Wake-on-LAN and post-job power policies are not implemented.
- Save sources and restore targets must pass existing block-device safety
  checks. Restore verifies any present manifest signature and all artifact digests before
  writing, then reads the destination back and verifies SHA-256.
- Do not use authoritative DHCP on a shared LAN. Use the isolated PXE VM lab
  described in tests/vm/README.md before testing destructive workflows.


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

1. On the Server, select the deployment interface and run PXE preflight.
   Prefer ProxyDHCP on an existing LAN; use isolated DHCP only on a dedicated
   subnet after confirming Feclora is authoritative there.
2. Activate PXE. Feclora stages the packaged BIOS/UEFI iPXE firmware and the
   Live boot payload into the TFTP/HTTP trees. BIOS and UEFI clients chainload
   iPXE and boot that Live environment.
3. For unattended preparation, open Server setup and upload the prewritten
   JSON answer file. The `repository_url` is read from the JSON itself. The
   Server validates the schema and publishes the answer over HTTP through
   Caddy under a generated job UUID. No age, minisign, Client MAC, USB identity
   medium, certificate, key or enrollment is requested by this form.
4. The operator can explicitly revoke the published answer from Cockpit.
   Automatic revocation on deployment cancellation/expiry is not connected
   yet. The Live boot now downloads and validates the answer JSON when the
   unattended kernel handoff is present. The first connected provider is NFS: Live mounts it read-only, resolves the
   disk by WWN/serial, rechecks that identity immediately before writing and
   invokes the existing whole-disk restore engine with read-back verification.
   Other repository adapters and hardware acceptance remain pending.
5. The existing Remote jobs workflow is a the Server-authenticated TLS
   workflow. It uses job-scoped Client MAC selection and local target approval; it is
   not the new identity-free PXE answer workflow and must not be used as proof
   that unattended answer execution is complete.

### Destructive-operation security boundary

The answer JSON is declarative data, not shell code. It identifies the image,
repository and stable whole-disk WWN/serial selector and explicitly requests
restore/start. The Server validates it before publication. The Live image downloads and validates the answer. NFS repository access,
unique target resolution and immediate pre-write identity revalidation are
connected for whole-disk restore. Other repository providers and physical
acceptance remain pending. A URL, DHCP lease, MAC address, job UUID or successful
download is not authorization by itself.

The current implementation downloads and validates the answer in Live and
connects NFS-backed whole-disk restore to the existing engine. The target is
revalidated immediately before writing and the result is read back. Other
repository schemes, cross-reboot replay/expiry controls and hardware acceptance
remain pending; test only with disposable disks.

### Durable Client progress and restart history

The Server journals bounded progress checkpoints received over the Server-authenticated TLS session. The first snapshot for a Client is persisted, followed by checkpoints after at least 1 MiB of additional progress or five seconds; phase and total-size changes are also persisted immediately. This bounds journal growth while retaining useful restart diagnostics. The Deployment history view reports the last durable checkpoint per Client, not a live rate estimate.

A progress checkpoint is an audit record, not a recovery cursor. After a Server process or host restart, Feclora does not reconnect the old Client session, continue a transfer, or resume disk I/O. The last recorded byte count may precede the actual point of interruption. Operators must inspect every Client and destination device and reconcile the interrupted job before creating a new one. A partially written destination remains potentially unusable.
