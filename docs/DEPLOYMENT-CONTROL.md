# Authenticated deployment control protocol

The initial Server/Client control-plane implementation is in
`feclora.deployment.control`. It uses the existing TLS helper and coordinator.

## Trust and enrollment

- TLS is restricted to TLS 1.3 and requires a certificate from the configured CA
  on both endpoints.
- The Server maps an exact client certificate SAN identity (URI, DNS, IP or
  EMAIL) or SHA-256 certificate fingerprint to one enrolled unicast MAC.
- The MAC is checked against the job allowlist only after certificate
  authentication. A MAC address, DHCP lease, PXE UUID or source IP is never an
  authentication factor.
- The Client pins the expected Server SAN identity or SHA-256 certificate
  fingerprint after CA validation.
- Enrollment/configuration distribution and certificate rotation/revocation
  are not yet implemented. Protect CA private keys and endpoint private keys
  outside the repository; never place them in PXE/TFTP/HTTP boot assets.

## Framing and lifecycle

Control messages are length-prefixed JSON with a 16 KiB maximum frame, strict
message types, duplicate-key rejection and exact field-set validation at each
state transition.

1. Client opens mTLS and sends HELLO with job UUID and its inventory MAC.
2. Server derives the certificate identity from the authenticated TLS peer,
   maps it to an enrolled MAC and checks the HELLO and job allowlist.
3. Server sends the validated immutable job document.
4. Client independently selects and confirms its local target through the
   caller-provided local authorization callback. Only a human-approved target
   description is sent to the Server; the target device path is not sent.
5. Server registers READY in the existing DeploymentCoordinator.
6. Operator calls the coordinator-backed arm operation. Only then does Server
   send START to READY clients.
7. Client invokes the caller-provided execution callback and returns a bounded
   per-client result. Server records the result in the coordinator.

The control module does not accept shell commands, remote device paths, or
arbitrary file paths. It does not perform image transfer or block-device I/O.
The execution callback is deliberately an integration seam, not a claim that
save/restore data transfer is complete.

## Implemented and remaining

Implemented:
- TLS 1.3 mTLS context enforcement and exact peer identity verification;
- identity-to-MAC enrollment mapping and job allowlist enforcement;
- framed HELLO/JOB/READY/START/RESULT/CANCEL control messages;
- coordinator registration, readiness, explicit arming, running and per-client
  result transitions;
- tests for framing, invalid messages, client start gating, coordinator
  integration and a loopback TLS 1.3 client/server handshake using ephemeral
  test certificates.

Still required:
- persistent job/session storage and restart recovery;
- secure certificate enrollment, revocation and rotation UI;
- Server-mode UI integration and runtime configuration/enrollment authoring;
- Client-mode UI, actual storage inventory selection and typed destructive
  confirmation;
- authenticated image-artifact data plane for save and restore, including
  signed manifest transfer, staging, disk_restore/capture integration and
  read-back verification;
- real PXE BIOS/UEFI VM boot and destructive operations on disposable virtual
  disks. The libvirt harness creates guests; it does not execute the tests
  automatically or imply they passed.

## PXE VM test lab

See [tests/vm/README.md](../tests/vm/README.md) and
[run-pxe-matrix.sh](../tests/vm/run-pxe-matrix.sh). The lab uses an isolated
libvirt network without libvirt DHCP so Feclora can be the only DHCP/PXE
authority. Never use authoritative DHCP on a shared network.
