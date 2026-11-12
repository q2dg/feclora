# Deployment control protocol

The Server/Client control plane uses TLS, the deployment coordinator and the
existing image-transfer and storage engines. TLS authenticates the Server to
each Client. Clients do not present certificates and the Server does not
authenticate individual Clients.

## Trust and job selection

- The Server presents its TLS certificate. Each Client validates its chain
  against the configured CA and checks the configured Server SAN identity (or
  certificate pin).
- The Server does not request or validate a Client certificate. There is no
  Client certificate enrollment, client identity mapping, per-Client token or
  client authentication.
- The job contains an explicit list of selected Client MAC addresses. A
  connecting Client reports its MAC and job UUID; the Server checks both
  against the active job. This is job scoping and inventory selection, not
  proof of Client identity.
- The job UUID correlates messages and state. It is not a credential.
- A Client selects its own target locally and types the exact READ or ERASE
  confirmation before READY. The Server operator must explicitly arm the job
  before any storage operation starts.
- TLS protects the control channel and remote clone stream. Image integrity
  is independently checked using manifest SHA-256 digests and, when
  configured, detached minisign signatures. Age encryption is optional and
  provides artifact confidentiality.

The managed CA/Server certificate setup is described in
[Certificate management](CERTIFICATE-MANAGEMENT.md). Never place the CA
private key or Server private key in PXE/TFTP/HTTP boot assets.

## Framing and lifecycle

Control messages are length-prefixed JSON with a 16 KiB maximum frame, strict
message types, duplicate-key rejection and exact field-set validation.

1. Client establishes TLS, verifies the Server certificate, and sends its MAC
   address and job UUID.
2. Server checks that the job UUID matches the active job and that the MAC is
   selected in that job. This check does not authenticate the Client.
3. Server sends the validated job document.
4. Client independently selects a local target and returns READY only after
   its local target checks and typed confirmation succeed. The selected
   device path and confirmation remain local except where a clone operation
   needs the receiver path to address the destination.
5. Server records READY. The operator explicitly arms the job; only then does
   Server send START.
6. For restore, Server sends the manifest and image artifacts over the
   Server-authenticated TLS channel. Client verifies artifact sizes and
   SHA-256 digests, checks a detached signature when one is present and
   independently trusted, stages the set privately, then invokes the
   protected restore engine with local confirmation and destination read-back.
7. For save, Client captures the locally selected disk without modifying it.
   Optional age encryption and minisign signing are selected per image. Server
   verifies every artifact before atomically publishing the image set.
8. Client returns a bounded result correlated with the job UUID. Server
   records the result in the job journal.

For multicast restore, each selected Client completes the same
Server-authenticated TLS HELLO/JOB/READY exchange and independently approves
its local disk and receive interface. Server refuses to arm unless every
selected Client is READY. UDPcast then sends the artifacts to all Clients.
UDPcast itself does not encrypt or authenticate datagrams; use a trusted,
isolated multicast segment. Manifest signatures and SHA-256 are checked before
disk writes. Enable age encryption when artifact confidentiality is required.

## Remote disk clone

Remote clone reuses the same Server-authenticated TLS control session. The
Server is the source; the Client is the receiver. Both operators make local
device choices and confirmations. There is no Client certificate identity
binding or mutual TLS. The receiver revalidates its block device, streams
bounded chunks, checks SHA-256 and reads back the written range before
reporting success. See [Remote disk clone](REMOTE-DISK-CLONE.md).

## Persistent service and recovery

The persistent Server service uses the existing coordinator, control listener,
storage engines, local root-only IPC and hash-chained job journal. It is not
enabled at boot and runs one job per Server. It never resumes a TLS session or
storage operation after a process crash.

A clean unarmed stop can be restarted only when no Client session was
recorded. An interrupted job requires manual inspection of every affected
device and explicit operator reconciliation. Reconciliation records an
operator assertion; it does not roll back, resume or verify storage writes.
Automated tests do not establish real-network or destructive-storage
acceptance.

## Implemented and remaining

Implemented:
- Server-authenticated TLS with CA and exact Server identity validation on
  Clients; no Client certificate request or client authentication;
- job UUID correlation, selected-MAC job scoping, READY/ARM/START/RESULT
  lifecycle and per-Client result journaling;
- bounded control framing, pending-connection cleanup and interface-scoped
  firewall lifecycle;
- unicast save/restore, multicast restore, artifact integrity checks and
  optional age/minisign integrations;
- remote disk clone over the existing control session with local device
  approval, bounded streaming, SHA-256 and receiver read-back;
- persistent Cockpit service, root-only local IPC and durable job journal.

Still required:
- physical multi-host acceptance for save, restore, multicast and remote clone;
- BIOS/UEFI PXE VM boot and failure/packet-loss acceptance;
- automated tests that execute capture/restore against disposable block
  devices over the network;
- multicast live progress, unicast multi-client fan-out, multicast save and
  post-job power policies.

## Optional cryptographic integrations

Age is an optional image-confidentiality layer. Minisign is the current
detached-manifest/profile signature implementation, but it is not a
mandatory installation dependency. SHA-256 detects corruption; without a
trusted signature it does not authenticate the publisher or prevent malicious
replacement. TLS authenticates the Server endpoint only, not individual
Clients.
