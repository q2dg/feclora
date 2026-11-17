---
layout: default
title: Server certificate and trust setup
---
<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

# Server certificate and trust setup

![Illustrative Server-to-Client certificate trust flow]({{ '/assets/mockups/certificate-trust.svg' | relative_url }})

*Illustrative mockup — not a screenshot. It shows the trust direction; the Client validates the Server certificate and the Server does not use a Client certificate for mutual TLS.*

Feclora uses TLS to authenticate the Server to each Client and protect the deployment control channel. The Server presents its certificate; Clients validate it against the configured CA and expected Server identity. Clients identify themselves to deployment jobs by reporting their MAC address. That value is an operational selector, not cryptographic proof of machine identity.

## 1. Understand the trust relationship

The TLS trust relationship is one-way: Clients verify the Server. The Server associates a connected Client with a deployment job using its reported MAC address. Do not describe this as mutual TLS or certificate-based Client authentication.

Image manifests record artifact byte counts and SHA-256 digests. Those checks detect artifact changes relative to the manifest, but do not authenticate the publisher. Repository access controls and the Server-authenticated TLS channel provide the applicable trust boundaries for their respective workflows. Optional age encryption protects image confidentiality, not Client identity.

## 2. Initialize the Server

1. Start the Feclora Server deployment service from Cockpit.
2. On first use, Feclora creates a local deployment CA and a Server TLS certificate/key, then writes the root-only Server configuration.
3. Open the trust details in Cockpit and record the displayed CA SHA-256 fingerprint through a trusted administrative channel.
4. Protect the CA private key on the Server. Back it up only using the organization's approved secret-management process.

## 3. Provision each Client

Provide each Client only:
- the CA certificate used to validate the Server certificate;
- the Server address and expected Server certificate SAN identity (normally `URI:feclora-server`);
- the operational deployment details, including the selected Client MAC address and job UUID.

Never copy the CA private key or Server private key to a Client. Never put private keys in TFTP/HTTP boot assets. Configure the Client to validate both the certificate chain and the expected Server identity; do not disable verification to work around a mismatch.

## 4. Use an organizational CA (optional)

External organizational PKI is also supported. Provision the Server certificate/key and corresponding CA certificate using the organization's normal secure process. Each Client must trust that CA and validate the configured Server identity. Confirm that the certificate SAN matches the identity configured on the Client.

## 5. Monitor expiry and rotate keys

The Server certificate and CA have finite validity. Monitor their expiry and renew or rotate the Server keypair through the managed Server PKI workflow. Rotation retains the configured CA, so Clients continue to validate the Server under the same trust anchor and identity. Do not replace or distribute private keys manually.

## Security boundaries

- MAC addresses are operational identifiers and can be spoofed.
- There is no trust-on-first-network-contact.
- The CA and Server private keys are not exported or transferred to Clients.
- No OCSP/CRL requirement or public Internet dependency is assumed.
- TLS keys are separate from optional age-encryption identities.

For the full deployment workflow, continue with the [Server and Client setup guide](./DEPLOYMENT-SETUP.html). For implementation status, see the [feature matrix](./FEATURE-MATRIX.html).
