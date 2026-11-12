# Server certificate and trust setup

Feclora uses TLS to let each Client verify the Server. Client certificates and
mutual TLS are not used. The Server does not authenticate individual Clients;
there is no Client certificate enrollment, renewal, revocation, client
identity mapping or per-Client credential.

## Security model

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

## Initial Server setup

On first Server use, Feclora creates a local deployment CA and a Server TLS
certificate/key, then writes the root-only Server configuration. The UI
displays the CA SHA-256 fingerprint. Record it and keep the CA private key
protected on the Server; an encrypted offline backup is recommended.

For each Client, provision only:
- the CA certificate used to validate the Server certificate;
- the Server address and expected Server certificate SAN identity (normally
  URI:feclora-server);
- the deployment job's operational details, including the Client's MAC
  address and job UUID when joining a job.

Never copy the CA private key or Server private key to a Client. Never put
private keys in TFTP/HTTP boot assets.

External organizational PKI is also supported. In that case, provision the
Server certificate/key and the corresponding CA certificate using the
organization's normal secure process. Each Client must trust that CA and
validate the configured Server identity.

## Encrypted offline CA backup

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Cockpit can verify an offline backup by decrypting it into a private temporary
directory and checking the expected entries, manifest, CA fingerprint,
constraints and private-key/certificate match. Verification is not restoration.
Restore is not exposed in Cockpit; do not copy files manually over a live
PKI directory.

## Key expiry and recovery

The Server certificate and CA have finite validity. Monitor their expiry and
renew or replace them through the Server's managed PKI workflow. Client
certificate expiry and fleet-wide Client revocation do not apply because
Clients have no certificates.

The CA private key is root-only but is not encrypted at rest in the Live
appliance. Protect persistent Server storage and keep an encrypted offline
backup. If the CA is lost or compromised, provision a replacement CA and
update the trusted CA certificate on every Client.

## Explicit non-goals

- No Client certificate enrollment, renewal or revocation.
- No mutual TLS, per-Client token or individual Client authentication.
- No trust-on-first-network-contact.
- No export or transfer of the CA or Server private key.
- No OCSP/CRL requirement or public Internet dependency.
- No conflation of TLS keys with optional image-signing or encryption keys.
