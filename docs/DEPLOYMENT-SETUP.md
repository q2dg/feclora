# Configuring authenticated Server and Client modes

The authenticated deployment runtime is opt-in. PXE services and the control
listener do not start automatically at boot. On first Server use, Feclora
creates a root-only local CA, Server TLS identity, minisign signing key and
age identity, then generates a default Server configuration. Client TLS and
age keys are generated locally during the guided enrollment workflow.
External organizational PKI remains supported.

See [Certificate management](CERTIFICATE-MANAGEMENT.md) for the USB-based CSR
approval ceremony, renewal, revocation and key-separation model.

## Filesystem preparation

Feclora creates these directories on first Server/Client enrollment. They
must remain root-owned and mode 0700. The Server creates
`/etc/feclora/deployment-server.json` automatically when it has no existing
configuration. Do not copy its CA private key to a Client.

The JSON configuration files must be root-owned regular files with mode 0600.
CA certificates, endpoint certificates and minisign public keys must be
root-owned regular files. TLS private keys and minisign secret keys must also
have no group/other permissions. Symlink paths are rejected.

For the Feclora-managed flow, use the Client mode **Prepare enrollment
request** and the Server's **Trusted Clients → Approve Client CSR** screen.
Private keys never leave their endpoint. The Server validates the CSR SAN,
signs it for 90 days, maps its identity to the operator-approved MAC and
registers the Client's age recipient. The Client verifies the CA fingerprint
and Server minisign public-key fingerprint before installing the response.
A restore-only Client does not need a minisign signing keypair. Do not put
private keys or trust material in TFTP/HTTP boot assets.

For an organization-issued CA, provision the endpoint TLS certificate/key
out of band and use **Import an externally issued Client certificate**.

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
  "client_identity_to_mac": {
    "URI:feclora-client-01": "52:54:00:12:34:56",
    "URI:feclora-client-02": "52:54:00:12:34:57"
  },
  "client_minisign_public_keys": {
    "52:54:00:12:34:56": "/etc/feclora/pki/client-01.pub",
    "52:54:00:12:34:57": "/etc/feclora/pki/client-02.pub"
  },
  "server_minisign_public_key": "/etc/feclora/pki/server.pub",
  "repository": "/var/lib/feclora/images"
}
~~~

The Server writes a private hash-chained job journal under /var/lib/feclora/deployments; the directory is created root-owned with mode 0700. On startup, verified journals reconstruct the last job/client states for operator review. This is audit-only recovery: live sessions are not recreated and destructive jobs are never resumed automatically.

For an interrupted job, the startup review offers an explicit operator reconciliation action. First inspect every Client and destination disk out of band; then select the acknowledgement and type exactly `RECONCILE <job-UUID>`. This appends a durable `operator_reconciled` event and closes the journal as failed, not successful. It does not retry, roll back, resume, or access any block device. Leaving the action pending is safe and prevents any implicit assumption about partial writes; Server refuses to create/arm another deployment until every interrupted journal has been reconciled.

The Server's **Trusted Clients** screen offers:
- **Approve Client CSR:** validate the Client-generated CSR, review the URI identity and MAC, issue a 90-day certificate, enroll the identity and add its age recipient to the Server inventory. The response bundle includes the CA certificate, Server minisign public key and current age recipients.
- **Import external certificate:** verify an organization-issued certificate for TLS client use, then bind its identity to the approved MAC.
- **Revoke:** remove the TLS identity/MAC authorization, optional Client minisign trust and the mapped age recipient from future image-encryption inventories.
- **Export updated age recipient inventory:** export the current public recipient list to removable media. On existing Clients, choose **Refresh age recipient inventory** to update their local capture recipients.

The Client warns within 30 days of certificate expiry and can prepare a renewal CSR using its existing TLS key. The Server must approve the renewal and the Client must install the returned bundle. CRL/OCSP checks and server-side expiry inventory are not implemented.

The bind address must exactly match the IPv4 address selected in Server mode.
The Server UI creates either a one-client unicast save/restore job or a multi-client multicast restore job and displays the job UUID. Each selected Client operator enters that UUID. The Server listener opens TCP/9443 only on the selected interface in Feclora's temporary firewalld zone. During multicast transfers it temporarily adds the UDPcast port pair and IGMP on that same interface. The listener and temporary firewall rules are removed when the job UI exits.

For restore, the Server selects a manifest in the repository with a detached
minisign signature and verifies it with server.pub before sending. For save,
the Server verifies the incoming Client image with the public key associated
with that Client MAC before publishing it.

## Client configuration

Install /etc/feclora/deployment-client.json on each Client:

~~~json
{
  "schema_version": 1,
  "host": "192.0.2.2",
  "port": 9443,
  "local_identity": "URI:feclora-client-01",
  "server_identity": "URI:feclora-server",
  "mac_address": "52:54:00:12:34:56",
  "ca_file": "/etc/feclora/pki/ca.crt",
  "certificate_file": "/etc/feclora/pki/client-01.crt",
  "private_key_file": "/etc/feclora/pki/client-01.key",
  "trusted_server_public_key": "/etc/feclora/pki/server.pub",
  "local_minisign_secret_key": "/etc/feclora/pki/client-01.key.minisign",
  "local_minisign_public_key": "/etc/feclora/pki/client-01.pub",
  "age_identity_file": "/etc/feclora/pki/client-01.age",
  "age_recipients_file": "/etc/feclora/pki/age-recipients.txt",
  "repository": "/var/lib/feclora/images"
}
~~~

The example above is configured for a Client that can both restore and save. A restore-only Client should set both `local_minisign_secret_key` and `local_minisign_public_key` to `null`; Feclora does not require or provision a Client signing secret unless that Client is authorized to create images.

Select Client mode, enter the job UUID shown by Server, select the local
whole disk or existing target partition as specified by the job, and type the exact operation-specific confirmation. For restore,
the phrase is ERASE /dev/DEVICE FROM URI:feclora-server. For save, it is
READ /dev/DEVICE TO URI:feclora-server. The /dev path and confirmation remain
local; only a human-readable disk description is sent to Server. The Client
must independently approve the target before sending READY.

## Scope and safety limits

- Unicast supports one authenticated Client per job: whole-disk save, and whole-disk or existing-partition restore.
- Multicast supports one-to-many **restore** of signed whole-disk or partition images to existing local targets on multiple authenticated Clients. The mTLS control plane authenticates every Client, obtains local target approval, distributes the signed manifest and records per-client results. Each Client stages privately and verifies the signed manifest, exact artifact size and SHA-256 before invoking the normal protected restore/read-back path. Partition targets are not created or resized.
- Multicast uses an administratively scoped 239.0.0.0/8 data group, a derived separate rendezvous group, an even UDPcast port base (the base and base+1 UDP ports plus IGMP are opened temporarily), TTL 1 and a 100 Mbit/s default sender limit. Each Client selects its own local receive interface; it need not have the same interface name as the Server.
- Multicast requires all selected Clients on the same multicast-enabled L2/VLAN segment, with switch IGMP snooping and a functioning querier. The current TTL=1 profile does not support routed cross-VLAN multicast. Use unicast when the network cannot meet these conditions.
- Multicast jobs accept only artifacts encrypted with age for the enrolled recipient set. The detached minisign signature authenticates the manifest and binds the exact ciphertext; age's authenticated encryption detects ciphertext modification on decryption. This is artifact-level protection, not per-datagram authentication: UDPcast metadata remains visible and an on-path attacker can still disrupt a transfer. The Server and Client perform local interface/route/tool preflight; switch IGMP snooping and querier configuration must still be verified by the operator.
- Multicast save, partition-image capture over the network, multi-client unicast, unattended target approval, automatic restart/resume of destructive writes, per-client live byte progress, Wake-on-LAN and post-job power policies are not implemented.
- Save sources and restore targets must pass existing block-device safety
  checks. Restore verifies the signed manifest and all artifact digests before
  writing, then reads the destination back and verifies SHA-256.
- Do not use authoritative DHCP on a shared LAN. Use the isolated PXE VM lab
  described in tests/vm/README.md before testing destructive workflows.


For a multi-Client restore, the Cockpit job form can select either the local
Server image repository or a mounted, verified SSHFS/NFS/SMB repository. The
job journal stores only the managed repository ID, not a path. The Server
resolves that ID again when the persistent deployment service starts, checks
the signed manifest, and streams from that mount to each authenticated READY
Client (unicast) or to the complete READY receiver set (UDPcast multicast).
Keep the repository mounted until all Client terminal results have been
collected. The remote repository's files must satisfy Feclora's root-owned
image-manifest checks; NFS root-squash may prevent this.
