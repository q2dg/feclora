# Authenticated deployment control protocol

The Server/Client control-plane implementation is in `feclora.deployment.control`. It uses TLS helpers and the existing DeploymentCoordinator. Signed whole-disk artifact transfer and local capture/restore callbacks are implemented in `artifact_transfer.py` and `client_runtime.py`.

## Trust and enrollment

- TLS is restricted to TLS 1.3 and requires a certificate from the configured CA on both endpoints.
- The Server maps an exact client certificate SAN identity (URI, DNS, IP or EMAIL) or SHA-256 certificate fingerprint to one enrolled unicast MAC.
- The MAC is checked against the job allowlist only after certificate authentication. A MAC address, DHCP lease, PXE UUID or source IP is never an authentication factor.
- The Client pins the expected Server SAN identity or SHA-256 certificate fingerprint after CA validation.
- Enrollment/configuration distribution and certificate rotation/revocation are not yet implemented. Protect CA private keys and endpoint private keys outside the repository; never place them in PXE/TFTP/HTTP boot assets.

## Framing and lifecycle

Control messages are length-prefixed JSON with a 16 KiB maximum frame, strict message types, duplicate-key rejection and exact field-set validation at each state transition.

1. Client opens mTLS and sends HELLO with job UUID, its inventory MAC and configured certificate identity.
2. Server derives the certificate identity from the authenticated TLS peer, maps it to an enrolled MAC and checks the HELLO and job allowlist.
3. Server sends the validated immutable job document.
4. Client returns a LocalTargetApproval binding its selected /dev path to the exact typed confirmation (ERASE for restore, READ for save). Only a human-readable target description is sent to Server; the path and confirmation remain local.
5. Server registers READY in DeploymentCoordinator. The operator explicitly arms the job; only then does Server send START.
6. For restore, Server sends a transfer offer and signed image set. Client verifies the minisign signature and each artifact's exact size/SHA-256, stages the set privately, then invokes the protected whole-disk restore workflow with a local typed ERASE confirmation and destination read-back.
7. For save, Client captures a locally selected read-only disk, signs its manifest, then sends the image set. Server verifies the enrolled Client minisign public key and every artifact before atomically publishing the set.
8. Client returns a bounded per-client result. Server records the result in the coordinator.

Image transfer uses the same authenticated TLS session. The receiver publishes artifacts first and the signed manifest/signature last as the image-set commit marker. No unauthenticated multicast path is involved in this unicast phase.

## Implemented and remaining

Implemented:
- TLS 1.3 mTLS context enforcement and exact peer identity verification;
- identity-to-MAC enrollment mapping and job allowlist enforcement;
- managed TCP listener start/stop lifecycle, pending-handshake cleanup, listener error reporting and interface-scoped firewalld port lifecycle;
- framed HELLO/JOB/READY/START/RESULT/CANCEL and transfer-offer/readiness messages;
- coordinator registration, readiness, explicit arming, running and per-client result transitions, plus a single-client end-to-end unicast job orchestrator;
- signed image-set transfer with manifest signature validation, exact artifact size/SHA-256 checks, private staging and no-overwrite publication;
- Client whole-disk save/restore callback integration with capture_disk and restore_disk, local typed confirmations, trusted minisign keys and destination read-back;
- Server and Client dialog workflows, root-owned runtime configuration validation, local inventory selection, typed confirmation, one-client job authoring/arming and per-client result display;\n- tests for framing, invalid messages, image transfer integrity, Client save/restore callbacks, scoped firewall lifecycle and a loopback TLS 1.3 client/server handshake using ephemeral test certificates.

Still required:
- Server-mode UI integration: job authoring, listener controls, repository selection and per-client progress/results;
- Client-mode UI: credential loading, storage inventory selection, local typed confirmation and repository selection;
- persistent job/session storage, crash recovery and safe handling of interrupted transfers;
- secure certificate and minisign-key enrollment, revocation and rotation UI;
- integration tests that execute real capture/restore against disposable block devices over mTLS;
- automated PXE BIOS/UEFI VM boot, Server/Client orchestration and full end-to-end acceptance. The libvirt harness creates guests; it does not execute the tests automatically or imply they passed.

## PXE VM test lab

See [tests/vm/README.md](../tests/vm/README.md) and [run-pxe-matrix.sh](../tests/vm/run-pxe-matrix.sh). The lab uses an isolated libvirt network without libvirt DHCP so Feclora can be the only DHCP/PXE authority. Never use authoritative DHCP on a shared network.