# Certificate and device enrollment policy

## Decision

Feclora manages its own deployment CA by default. External organizational PKI
remains supported for managed environments. Certificate administration is
only required for Server/Client networking; local rescue and offline imaging
remain usable without certificates, a CA, Cockpit or a network service.

## Security model

- The Server owns a root-only Feclora CA private key and a separate TLS Server
  private key. Neither is copied to Clients or PXE/HTTP assets.
- Every Client generates its TLS private key locally and exports only a CSR.
  The Server signs that CSR after explicit operator approval.
- Every Client also generates a local age identity. Only its public age
  recipient is exported. The Server maintains a recipient inventory used to
  encrypt image artifacts for the Server and enrolled Clients.
- Client certificates use a stable URI SAN
  `URI:feclora-client-<id>`, TLS client-auth EKU and 90-day validity.
  The Server identity is `URI:feclora-server` with server-auth EKU.
- mTLS authenticates endpoint identity. The Server's enrolled-identity/MAC
  mapping and per-job allowlist authorize participation. A MAC address is
  inventory metadata, never authentication.
- The Server minisign key, TLS CA/endpoint keys and age identities are
  separate cryptographic roles and must never be substituted for one another.

## Operator workflow

1. On first entry to Server deployment mode, Feclora creates the CA, Server
   TLS identity, minisign image-signing key and Server age identity. The UI
   displays the CA SHA-256 fingerprint. Record it and back up the CA key
   encrypted and offline.
2. On a Client with no deployment config, choose **Prepare enrollment
   request**. Feclora creates the Client TLS key and age identity locally,
   then exports the CSR and public age recipient to removable media. Private
   keys remain on that Client.
3. On the Server, choose **Trusted Clients → Approve Client CSR**. Review the
   CSR identity, assign its unicast MAC, and explicitly confirm issuance.
   Feclora signs the CSR, adds the Client to the TLS allowlist and age
   recipient inventory, and exports the Client certificate, CA certificate,
   Server minisign public key and current age recipient list.
4. On the Client, choose **Complete enrollment**. Enter the Server address
   and MAC, verify the CA fingerprint and the Server minisign-key SHA-256
   fingerprint against the values displayed by the Server, then install the
   bundle. Feclora checks the CA chain, SAN identity and that the certificate
   matches the private key already held locally.
5. The Client can now join authenticated deployment jobs. It warns when its
   certificate is within 30 days of expiry and offers a renewal CSR using the
   existing private key. The Server signs the renewal; the Client installs the
   replacement certificate without changing its identity.

This is an intentionally physical bootstrap ceremony. Feclora never trusts a
Client merely because it appears on DHCP/PXE or presents a MAC address.

## Encrypted offline CA backup

The Server Cockpit **Server setup** tab can export an encrypted CA recovery
archive to a mounted removable-media directory. Supply an age public recipient
whose corresponding private identity is held separately, preferably offline
and under a different administrative control. The archive contains only
`ca.key`, `ca.crt`, and a versioned manifest with the CA fingerprint; it
does not contain Server endpoint keys, Client keys, minisign keys, or age
identities. The CA private key is never staged unencrypted outside the
root-only PKI directory. The resulting `.tar.age` file is mode 0600, published
without overwriting an existing backup, and its SHA-256 is shown for
verification.

Keep the age decryption identity separate from the removable media containing
the backup. Losing that identity makes the backup unrecoverable; storing it
beside the backup defeats the offline protection. Test decryption and archive
inspection in a controlled recovery environment before relying on a backup.

Cockpit now provides **Verify an offline CA backup**. Select the encrypted
archive and its matching age identity from mounted removable media. Feclora
decrypts into a private temporary directory, accepts only the exact three
expected regular-file entries, validates the versioned manifest and CA
fingerprint, checks CA basic constraints/key usage and confirms the private
key matches the certificate. It removes temporary plaintext on exit and does
not alter live PKI material. The identity file must be root-owned and mode
0600 or stricter; the encrypted archive is limited to 16 MiB.

**Restore is not yet exposed in Cockpit.** Verification is not restoration and
does not prove that the rest of the Server state can be recovered. Do not copy
files manually over a live `/etc/feclora/pki` directory. A future restore
workflow must verify the archive, stop all deployment services, preserve an
encrypted pre-restore snapshot, and require explicit confirmation before
installing the restored CA.

## Renewal, revocation and recovery

- Client renewal preserves the existing TLS private key and stable identity.
  The Server issues a new 90-day certificate after explicit CSR approval.
- Revoking a Client removes its identity-to-MAC authorization and its age
  recipient from the Server's recipient inventory, so future images are not
  encrypted for that identity. Images already encrypted for that recipient
  remain decryptable by it; revocation cannot retroactively revoke old copies.
- Existing TLS sessions are not dynamically revoked by the allowlist. The
  current UI performs trust administration before arming a job; do not use
  it as an in-flight session termination control.
- The Client receives a snapshot of the age recipient inventory at
  enrollment/renewal. If the inventory changes later, export the current
  `age-recipients.txt` from the Server's Cockpit trust panel and use
  the Client's Cockpit enrollment panel to verify and atomically refresh it.
  This remains a manual removable-media exchange; there is no network push.
- The CA private key is root-only but is not encrypted at rest in the Live
  appliance. Protect persistent Server storage and keep an encrypted offline
  backup. If lost or compromised, create a new CA and re-enroll every
  endpoint.
- CRL validation, server-certificate renewal automation, server-side expiry
  inventory and OCSP are not implemented. The Client warns locally about its
  own certificate expiry. OCSP is not required for an isolated appliance.
- External PKI remains supported through the existing certificate-import
  workflow; Feclora-managed CSR issuance is only enabled when the configured
  CA is the local Feclora CA.

## Current implementation boundaries

Implemented: first-run CA/Server bootstrap, endpoint-local TLS and age key
creation, CSR signing, CA and minisign-key fingerprint checks, Client
certificate installation, the existing removable-media Client renewal
primitives, Server allowlist enrollment and revocation, per-Client age
recipient registration/removal, Cockpit Server-side CSR inspection/approval
with public response-bundle export, Cockpit trusted-Client inventory and
exact-confirmation revocation, plus Cockpit Server export and Client-side
verification/atomic refresh of the age recipient snapshot, and encrypted
removable-media backup of the managed CA.

Not yet implemented: staged CA rotation and Client trust migration, CA backup
restore, minisign signing-key rotation, age identity/recipient rotation,
CRL/OCSP validation, server-side certificate last-seen inventory, or automatic
network push of age recipient snapshots to already-enrolled Clients.

## Explicit non-goals

- No trust-on-first-network-contact or MAC-only authentication.
- No export or transfer of endpoint TLS private keys.
- No OCSP or public Internet dependency.
- No conflation of TLS, minisign and age keys.
