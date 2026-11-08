# Certificate and device enrollment policy

## Decision

Feclora should manage the ordinary deployment PKI itself. Requiring a home or
small-lab operator to install an external CA, create CSRs, understand SANs, and
maintain certificate databases is disproportionate for a rescue/deployment
appliance. External organizational PKI remains an optional integration for
managed environments.

Certificate management is relevant only to Server/Client networking. Local
rescue and offline disk imaging must not require certificates, a CA, Cockpit,
or a network service.

## Security model

- The Server owns one Feclora deployment CA. Its private key is root-only and
  must never be copied to Clients, PXE/TFTP/HTTP assets, or the image repository.
- Each endpoint creates its own TLS private key locally. Private keys never
  leave the endpoint that created them.
- A Client is enrolled by exchanging a certificate-signing request (CSR), not
  its private key. The Server signs the CSR and returns the Client certificate
  and CA certificate. A removable device is the initial, deliberately
  out-of-band trust channel; a future pairing workflow may replace this with a
  short-lived, single-use enrollment token after its threat model is reviewed.
- The Server certificate is issued by the same Feclora CA. Clients trust that
  CA and pin the Server's configured SAN identity.
- Every Client certificate has a stable, unique URI SAN such as
  `URI:feclora-client-<id>`, a short validity period (target: 90 days), and
  the TLS client-auth extended key usage. The Server certificate has
  `URI:feclora-server` and TLS server-auth usage.
- mTLS proves endpoint identity. The Server's explicit enrolled-identity and
  job allowlists authorize a Client to participate. A MAC address is inventory
  metadata and an additional policy key, never authentication.
- The Server's minisign key signs image manifests; it is distinct from the TLS
  CA and TLS endpoint keys. A Client that only restores images does not need a
  minisign signing key.

## User experience

The intended Server workflow is:

1. On first entry to Server mode, Feclora creates its local CA and Server
   identity if they do not already exist. The UI displays the CA fingerprint
   and asks the operator to record/verify it.
2. On a Client, choose **Prepare enrollment**. Feclora creates the Client TLS
   key locally and exports a CSR plus a human-readable device identity to a
   removable drive. The private key remains on that Client.
3. On the Server, choose **Enroll Client**, import the CSR, review the
   requested device identity and assign the Client to an inventory/MAC entry.
   Feclora signs the CSR and exports the certificate and CA certificate.
4. Back on the Client, import the signed certificate bundle. Feclora checks
   that the certificate matches the locally held private key and the expected
   CA/SAN before enabling Client mode.
5. The Server's **Trusted Clients** screen lists enrolled Clients, expiry
   dates, last-seen status and permitted capabilities. The operator can
   disable/revoke one Client without editing JSON or running OpenSSL.

This bootstrap deliberately requires physical access or an equivalent
administrator-controlled secure transfer. Automatically trusting an
unauthenticated Client that merely appears on PXE would defeat mTLS.

## Renewal, revocation, and recovery

- Feclora should warn before expiry and support a one-click renewal request
  using the existing Client key. Renewal replaces the certificate, not the
  identity.
- Removing a Client from the Server's identity-to-MAC allowlist is the
  immediate application-level revocation mechanism: a still-valid CA-signed
  certificate is no longer authorized for a new deployment session.
- The Server should maintain an auditable revocation/disable record rather
  than silently deleting identity history. Existing TLS sessions must be
  terminated when a Client is revoked.
- CRL support is a defence-in-depth enhancement for CA-level revocation and
  CA compromise response. OCSP is not required for an isolated Live appliance.
  Until CRL validation is implemented, Feclora must not claim that it checks
  certificate revocation status at the TLS layer.
- Back up the CA private key encrypted and offline. If it is lost, existing
  certificates cannot be renewed; generate a new CA and re-enroll endpoints.
  If it is compromised, rotate the CA and re-enroll every endpoint.
- External PKI remains available: operators can continue importing
  organization-issued certificates and CA certificates instead of using the
  Feclora-managed CA.

## Implementation status

The current Server UI can enroll, rotate, and remove Client certificate
identities from its allowlist, but certificate issuance, private-key creation,
Client-side provisioning, expiry inventory, and CRL/OCSP validation are not
implemented. Current setup therefore still requires an external CA and
out-of-band provisioning. The design above is the target UX, not a claim about
the current executable.

## Explicit non-goals

- No automatic trust based only on MAC address, DHCP, PXE UUID, IP address, or
  first network contact.
- No transfer of TLS private keys from Server to Client.
- No requirement for OCSP or a public Internet connection.
- No conflation of TLS certificates, minisign image-signing keys, and age
  encryption identities.
