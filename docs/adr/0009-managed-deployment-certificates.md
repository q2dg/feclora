# ADR 0009: Feclora-managed deployment certificates

- Status: Accepted
- Date: 2026-11-08

## Context

Server/Client deployment uses TLS 1.3 mutual authentication. The current
implementation expects an externally provisioned CA and endpoint certificates.
That is secure when an organization already operates a PKI, but it makes a
small-lab Feclora installation unnecessarily difficult: operators must create
SAN-bearing certificates, distribute matching private keys, and maintain
renewal procedures.

Certificate administration is only needed for networked Server/Client
operations. Local rescue must remain usable offline without PKI setup.

## Decision

Provide a Feclora-managed local CA as the default enrollment option, while
retaining compatibility with externally issued certificates.

The Server owns the CA signing key. Each endpoint generates its own TLS key
locally and submits only a CSR. The Server signs the CSR after an explicit
operator approval; the signed certificate and CA certificate are returned to
the endpoint through a physical or otherwise administrator-controlled
out-of-band channel. No endpoint private key is exported or sent over PXE.

The initial implementation should use short-lived endpoint certificates,
stable unique URI SAN identities, explicit TLS EKUs, expiry warnings, and
renewal using the endpoint's existing key. The Server's enrolled identity
allowlist remains the authorization control; MAC addresses are never
authenticators. Revocation must terminate existing sessions and prevent new
sessions. CRL checking is defence in depth; OCSP is not a requirement for an
offline appliance.

The UI must expose ordinary operations as **Prepare enrollment**, **Approve
Client**, **Renew**, and **Revoke**. OpenSSL commands, certificate paths, SAN
syntax, and private-key files are implementation details, not operator tasks.

## Consequences

- External organizational PKI remains supported for managed environments.
- Local rescue and offline imaging do not depend on the CA.
- The CA key needs secure root-only storage and an encrypted offline backup.
- Initial trust bootstrap still requires physical access or another trusted
  administrator-controlled channel. Automatically trusting a device merely
  because it appears on PXE is explicitly prohibited.
- The current implementation is not yet compliant with this ADR: it supports
  allowlist enrollment/revocation of externally issued certificates, but not
  CA issuance, Client key provisioning, expiry inventory, or CRL validation.
  See [Certificate management](../CERTIFICATE-MANAGEMENT.md).

