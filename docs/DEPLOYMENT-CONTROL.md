# Authenticated deployment control protocol

The Server/Client control-plane implementation is in `feclora.deployment.control`. It uses TLS helpers and the existing DeploymentCoordinator. Signed whole-disk artifact transfer and local capture/restore callbacks are implemented in `artifact_transfer.py` and `client_runtime.py`.

## Trust and enrollment

The operator-facing target for certificate issuance and lifecycle is documented in [Certificate management](CERTIFICATE-MANAGEMENT.md) and [ADR 0009](adr/0009-managed-deployment-certificates.md). The current implementation still relies on an external CA and endpoint provisioning; its allowlist revocation is not CRL/OCSP revocation.

- TLS is restricted to TLS 1.3 and requires a certificate from the configured CA on both endpoints.
- The Server maps an exact client certificate SAN identity (URI, DNS, IP or EMAIL) or SHA-256 certificate fingerprint to one enrolled Client MAC.
- The MAC is checked against the job allowlist only after certificate authentication. A MAC address, DHCP lease, PXE UUID or source IP is never an authentication factor.
- The Client pins the expected Server SAN identity or SHA-256 certificate fingerprint after CA validation.
- Server UI supports CA-verified Client certificate enrollment/rotation and revocation, including an optional Client minisign public key. CA issuance, private-key generation/distribution, CRL/OCSP and Client-side private-key provisioning remain out of band. Protect CA private keys and endpoint private keys outside the repository; never place them in PXE/TFTP/HTTP boot assets.

## Framing and lifecycle

Control messages are length-prefixed JSON with a 16 KiB maximum frame, strict message types, duplicate-key rejection and exact field-set validation at each state transition.

1. Client opens mTLS and sends HELLO with job UUID, its inventory MAC and configured certificate identity.
2. Server derives the certificate identity from the authenticated TLS peer, maps it to an enrolled MAC and checks the HELLO and job allowlist.
3. Server sends the validated immutable job document.
4. Client returns a LocalTargetApproval binding its selected /dev path to the exact typed confirmation (ERASE for restore, READ for save). Only a human-readable target description is sent to Server; the path and confirmation remain local.
5. Server registers READY in DeploymentCoordinator. The operator explicitly arms the job; only then does Server send START.
6. For restore, Server sends a transfer offer and signed image set. Client verifies the minisign signature and each artifact's exact size/SHA-256, stages the set privately, then invokes the protected whole-disk restore workflow with a local typed ERASE confirmation and destination read-back.
7. For save, Client captures a locally selected disk without modifying it, signs its manifest, then sends the image set. Server verifies the enrolled Client minisign public key and every artifact before atomically publishing the set.
8. Client returns a bounded per-client result. Server records the result in the coordinator.

For multicast restore, every selected Client first completes the same mTLS HELLO/JOB/READY exchange and independently selects/authorizes its local disk and receive interface. Server refuses to arm unless every selected Client is READY. After explicit arming, Server sends the signed manifest and detached signature over the authenticated control channel; UDPcast then sends each artifact to all Clients using a 239.0.0.0/8 data group and a distinct derived rendezvous group. Each Client stages the full image set privately, verifies the signature and every size/SHA-256, then invokes the same protected restore/read-back path. UDPcast bytes are not treated as authenticated and are never written directly to a block device.
UDPcast does not authenticate or encrypt the artifact data plane. Manifest signatures and SHA-256 digests provide integrity checks before disk writes, not confidentiality or receiver identity. Use a trusted isolated multicast segment and age-encrypt image artifacts when confidentiality is required.

## Implemented and remaining

Implemented:
- TLS 1.3 mTLS context enforcement and exact peer identity verification;
- identity-to-MAC enrollment mapping and job allowlist enforcement;
- managed TCP listener start/stop lifecycle, pending-handshake cleanup, listener error reporting and interface-scoped firewalld port lifecycle;
- framed HELLO/JOB/READY/START/RESULT/CANCEL and transfer-offer/readiness messages;
- coordinator registration, readiness, explicit arming, running and per-client result transitions, one-client unicast orchestration and multi-client UDPcast whole-disk restore orchestration;
- private append-only SHA-256 hash-chained job journal; coordinator transitions are fsync-persisted before in-memory state changes, journal failures fail closed, prior events replay into per-client audit state, and interrupted jobs require an explicit operator reconciliation acknowledgement;
- signed image-set transfer with manifest signature validation, exact artifact size/SHA-256 checks, private staging and no-overwrite publication;
- Client whole-disk save/restore callback integration with capture_disk and restore_disk, local typed confirmations, trusted minisign keys and destination read-back;
- Server and Client dialog workflows, root-owned runtime configuration validation, local inventory selection, typed confirmation, unicast and multi-client multicast restore job authoring/arming, Client-local multicast interface selection and per-client result display;
- tests for framing, invalid messages, image transfer integrity, Client save/restore callbacks, scoped firewall lifecycle and a loopback TLS 1.3 client/server handshake using ephemeral test certificates.

Still required:
- automated integration tests that execute real capture/restore against disposable block devices over mTLS and UDPcast;
- automated PXE BIOS/UEFI VM boot, multi-client multicast execution, packet-loss/interrupt scenarios and full end-to-end acceptance. The libvirt harness and runbooks create/describe the lab; they do not execute the tests automatically or imply they passed;
- automated multicast network capability detection, per-client live progress, unicast multi-client fan-out, multicast save, CRL/OCSP integration, certificate/key provisioning and rotation on Client endpoints, and post-job power policies.
## PXE VM test lab

See [tests/vm/README.md](../tests/vm/README.md) and [run-pxe-matrix.sh](../tests/vm/run-pxe-matrix.sh). The lab uses an isolated libvirt network without libvirt DHCP so Feclora can be the only DHCP/PXE authority. Never use authoritative DHCP on a shared network.