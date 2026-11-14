# Server certificate and trust setup

Feclora uses TLS to authenticate the Server to each Client and protect the
deployment control channel. The Server presents its certificate; Clients
validate it against the configured CA and expected Server identity. Clients
identify themselves to deployment jobs by reporting their MAC address. The
Server uses that value for job selection and status association only; it is
not cryptographic proof of a machine's identity.

## Security model

The TLS trust relationship is one-way: Clients verify the Server. Deployment
sessions are associated with the MAC address reported by each Client.

Image manifests record artifact byte counts and SHA-256 digests. Those checks
detect artifact changes relative to the manifest, but do not authenticate the
publisher. Repository access controls and the Server-authenticated TLS channel
provide the applicable trust boundaries for their respective workflows. Age
encryption is optional and protects image confidentiality, not Client identity.

## Initial Server setup

On first Server use, Feclora creates a local deployment CA and a Server TLS
certificate/key, then writes the root-only Server configuration. The UI
displays the CA SHA-256 fingerprint. Keep the CA private key protected on the
Server.

For each Client, provision only:
- the CA certificate used to validate the Server certificate;
- the Server address and expected Server certificate SAN identity (normally
  `URI:feclora-server`);
- the operational deployment details, including the selected Client MAC
  address and job UUID.

Never copy the CA private key or Server private key to a Client. Never put
private keys in TFTP/HTTP boot assets.

External organizational PKI is also supported. In that case, provision the
Server certificate/key and corresponding CA certificate using the
organization's normal secure process. Each Client must trust that CA and
validate the configured Server identity.

## Key expiry and rotation

The Server certificate and CA have finite validity. Monitor their expiry and
renew or rotate the Server keypair through the managed Server PKI workflow.
Rotation retains the configured CA, so Clients continue to validate the
Server under the same trust anchor and identity.

## Explicit boundaries

- MAC addresses are operational identifiers and can be spoofed.
- No trust-on-first-network-contact.
- No export or transfer of the CA or Server private key.
- No OCSP/CRL requirement or public Internet dependency.
- TLS keys are separate from optional age-encryption identities.
