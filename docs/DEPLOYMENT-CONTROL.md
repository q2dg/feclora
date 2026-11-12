# Deployment control protocol

The Server/Client control plane uses TLS, the deployment coordinator and the
existing image-transfer and storage engines. TLS authenticates the Server to
each Client. Clients do not present certificates and the Server does not
authenticate individual Clients.

## Trust and job selection

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

The managed CA/Server certificate setup is described in
[Certificate management](CERTIFICATE-MANAGEMENT.md). Never place the CA
private key or Server private key in PXE/TFTP/HTTP boot assets.

## Framing and lifecycle

Control messages are length-prefixed JSON with a 16 KiB maximum frame, strict
message types, duplicate-key rejection and exact field-set validation.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

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

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Still required:
- physical multi-host acceptance for save, restore, multicast and remote clone;
- BIOS/UEFI PXE VM boot and failure/packet-loss acceptance;
- automated tests that execute capture/restore against disposable block
  devices over the network;
- multicast live progress, unicast multi-client fan-out, multicast save and
  post-job power policies.

## Optional cryptographic integrations

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.