# Configuring authenticated Server and Client modes

The authenticated unicast runtime is opt-in. PXE services and the control
listener do not start automatically at boot. Provision endpoint credentials
and configuration files out of band before selecting deployment mode.

## Filesystem preparation

On each Feclora Live endpoint, create the configuration and key directories
as root. Keep private keys and endpoint configuration readable only by root.

~~~bash
sudo install -d -o root -g root -m 0700 /etc/feclora /etc/feclora/pki
sudo install -d -o root -g root -m 0700 /var/lib/feclora/images
~~~

The JSON configuration files must be root-owned regular files with mode 0600.
CA certificates, endpoint certificates and minisign public keys must be
root-owned regular files. TLS private keys and minisign secret keys must also
have no group/other permissions. Symlink paths are rejected.

Create a private CA and issue separate Server and Client certificates using
your organization's PKI procedure. Each certificate must contain one stable
SAN identity, for example URI:feclora-server or URI:feclora-client-01.
Every endpoint validates the CA chain and then pins the exact expected SAN
identity. The Server additionally maps each Client certificate identity to
one enrolled unicast MAC address. MAC is an allowlist/inventory key, not
authentication. A Client that is restore-only does not need a minisign keypair;
its MAC is simply omitted from client_minisign_public_keys on the Server.

Generate a minisign key pair for the Server and one for each Client that may
save images. Distribute only the relevant public keys to the opposite
endpoint. Do not put private keys or trust material in TFTP/HTTP boot assets.

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
    "URI:feclora-client-01": "52:54:00:12:34:56"
  },
  "client_minisign_public_keys": {
    "52:54:00:12:34:56": "/etc/feclora/pki/client-01.pub"
  },
  "server_minisign_public_key": "/etc/feclora/pki/server.pub",
  "repository": "/var/lib/feclora/images"
}
~~~

The Server writes a private hash-chained job journal under /var/lib/feclora/deployments; the directory is created root-owned with mode 0700. On startup, verified journals reconstruct the last job/client states for operator review. This is audit-only recovery: live sessions are not recreated and destructive jobs are never resumed automatically.

For an interrupted job, the startup review offers an explicit operator reconciliation action. First inspect every Client and destination disk out of band; then select the acknowledgement and type exactly `RECONCILE <job-UUID>`. This appends a durable `operator_reconciled` event and closes the journal as failed, not successful. It does not retry, roll back, resume, or access any block device. Leaving the action pending is safe and prevents any implicit assumption about partial writes.

The Server now offers a **Client certificate trust** screen before creating a job:
- **Enroll/rotate:** provide a root-owned PEM Client certificate, its authorized unicast MAC, and optionally a root-owned minisign public key. Feclora verifies the certificate chain with `openssl verify -purpose sslclient`, extracts its single SAN identity, and requires the exact `ENROLL <identity> <mac>` confirmation. Re-enrolling the same MAC rotates the certificate identity.
- **Revoke:** select an enrolled identity and type `REVOKE <identity>`. The identity-to-MAC mapping and its associated Client minisign public key are removed atomically.
- **Restore-only Client:** leave the minisign public-key path blank. A Client authorized to save must be enrolled with its public key.

The UI never generates, imports, exports, or transmits private keys and does not issue certificates. A trusted CA must issue Client certificates out of band; the Client's matching private key must be provisioned securely on that Client. Certificate expiry/renewal and CA revocation-list/OCSP policy remain responsibilities of the external PKI. Rotation takes effect for new TLS handshakes; an already established session must be stopped.

The bind address must exactly match the IPv4 address selected in Server mode.
The Server UI creates a one-client job, selects save or restore, and displays
the job UUID. The Client operator enters that UUID. The Server listener opens
TCP/9443 only on the selected interface in Feclora's temporary firewalld zone.
The listener is stopped and its temporary firewall rule is removed when the
job UI exits.

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
  "age_identity_file": null,
  "age_recipients_file": null,
  "repository": "/var/lib/feclora/images"
}
~~~

The example above is configured for a Client that can both restore and save. A restore-only Client should set both `local_minisign_secret_key` and `local_minisign_public_key` to `null`; Feclora does not require or provision a Client signing secret unless that Client is authorized to create images.\n\nSelect Client mode, enter the job UUID shown by Server, select the local
whole disk and type the exact operation-specific confirmation. For restore,
the phrase is ERASE /dev/DEVICE FROM URI:feclora-server. For save, it is
READ /dev/DEVICE TO URI:feclora-server. The /dev path and confirmation remain
local; only a human-readable disk description is sent to Server. The Client
must independently approve the target before sending READY.

## Scope and safety limits

- This first runtime supports one authenticated Client per job and unicast
  whole-disk save/restore only.
- It does not implement partition deployment, concurrent multi-client jobs,
  multicast, unattended target approval, live session restart or destructive job resume (the journal provides audit-only recovery), or automatic key distribution.
- Save sources and restore targets must pass existing block-device safety
  checks. Restore verifies the signed manifest and all artifact digests before
  writing, then reads the destination back and verifies SHA-256.
- Do not use authoritative DHCP on a shared LAN. Use the isolated PXE VM lab
  described in tests/vm/README.md before testing destructive workflows.
