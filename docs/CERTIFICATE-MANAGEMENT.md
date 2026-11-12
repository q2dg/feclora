# Server certificate and trust setup

Feclora uses TLS to let each Client verify the Server. Client certificates and
mutual TLS are not used. The Server does not authenticate individual Clients;
deployment jobs select Clients by MAC address.

## Security model

Feclora does not sign image manifests or use detached signature sidecars.
Artifact integrity is checked with the byte count and SHA-256 digest recorded
in the manifest; authenticity relies on the protected local repository and
authenticated transport. Age encryption remains optional.

## Initial Server setup

On first Server use, Feclora creates a local deployment CA and a Server TLS
certificate/key, then writes the root-only Server configuration. The UI
displays the CA SHA-256 fingerprint. Keep the CA private key protected on the
Server.

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

## Key expiry

The Server certificate and CA have finite validity. Monitor their expiry and
renew or replace them through the Server's managed PKI workflow. Client
certificate expiry and fleet-wide Client revocation do not apply because
Clients have no certificates.

## Explicit non-goals

- No Client certificate enrollment, renewal or revocation.
- No mutual TLS, per-Client token or individual Client authentication.
- No trust-on-first-network-contact.
- No export or transfer of the CA or Server private key.
- No OCSP/CRL requirement or public Internet dependency.
- No PKI backup or restore workflow.
- No conflation of TLS keys with optional image-signing or encryption keys.
