# Authenticated deployment control protocol

The Server/Client control-plane implementation is in `feclora.deployment.control`. It uses TLS helpers and the existing DeploymentCoordinator. Image-set transfer and local capture/restore callbacks are implemented in `artifact_transfer.py` and `client_runtime.py`. Detached minisign signatures are verified when present; unsigned image sets are accepted only inside the authenticated mTLS session.

## Trust and enrollment

The managed local CA and Server identity bootstrap are documented in [Certificate management](CERTIFICATE-MANAGEMENT.md) and [ADR 0009](adr/0009-managed-deployment-certificates.md). Client CSR approval, certificate issuance/import, and Client-side certificate installation are exposed through Cockpit and the text-mode Client workflow. The current allowlist revocation is not CRL/OCSP revocation.

- TLS is restricted to TLS 1.3 and requires a certificate from the configured CA on both endpoints.
- The Server maps an exact client certificate SAN identity (URI, DNS, IP or EMAIL) or SHA-256 certificate fingerprint to one enrolled Client MAC.
- The MAC is checked against the job allowlist only after certificate authentication. A MAC address, DHCP lease, PXE UUID or source IP is never an authentication factor.
- The Client pins the expected Server SAN identity or SHA-256 certificate fingerprint after CA validation.
- Server-side primitives support CA-verified Client CSR inspection, certificate issuance/import, renewal, rotation and allowlist revocation. Age recipient and Client minisign public-key registration are optional image-security features. Protect CA private keys and endpoint private keys outside the repository; never place them in PXE/TFTP/HTTP boot assets.

## Framing and lifecycle

Control messages are length-prefixed JSON with a 16 KiB maximum frame, strict message types, duplicate-key rejection and exact field-set validation at each state transition.

1. Client opens mTLS and sends HELLO with job UUID, its inventory MAC and configured certificate identity.
2. Server derives the certificate identity from the authenticated TLS peer, maps it to an enrolled MAC and checks the HELLO and job allowlist.
3. Server sends the validated immutable job document.
4. Client returns a LocalTargetApproval binding its selected /dev path to the exact typed confirmation (ERASE for restore, READ for save). Only a human-readable target description is sent to Server; the path and confirmation remain local.
5. Server registers READY in DeploymentCoordinator. The operator explicitly arms the job; only then does Server send START.
6. For restore, Server sends a transfer offer and authenticated image set. Client receives the manifest over the authenticated mTLS session. If a detached signature is present, it must verify against an independently trusted public key; otherwise the authenticated TLS peer and session bind the manifest to the authorized Server. It verifies every artifact's exact size/SHA-256, stages the set privately, then invokes the protected restore workflow with a local typed ERASE confirmation and destination read-back. Encrypted artifacts additionally require the configured age identity.
7. For save, Client captures a locally selected disk without modifying it. Before capture, the Client operator selects compression and the image-security mode (none, age, minisign or both); unavailable tools/keys are not offered. If signing is enabled, the Client signs the manifest and the Server verifies it against the Client's enrolled public key; otherwise the mTLS-authenticated Client session binds the manifest to the enrolled identity. The Server verifies every artifact before atomically publishing the set.
8. Client returns a bounded per-client result. Server records the result in the coordinator.

For multicast restore, every selected Client first completes the same mTLS HELLO/JOB/READY exchange and independently selects/authorizes its local disk and receive interface. Server refuses to arm unless every selected Client is READY. After explicit arming, Server sends the manifest and optional detached signature over the authenticated control channel; UDPcast then sends each artifact to all Clients using a 239.0.0.0/8 data group and a distinct derived rendezvous group. Each Client stages the full image set privately, verifies any present signature and every size/SHA-256, then invokes the same protected restore/read-back path. UDPcast bytes are not treated as authenticated and are never written directly to a block device.
UDPcast does not authenticate or encrypt the artifact data plane. Manifest signatures and SHA-256 digests provide integrity checks before disk writes, not confidentiality or receiver identity. Use a trusted isolated multicast segment. `age` encryption is optional and should be enabled when confidentiality is required; it must not be a mandatory dependency for ordinary Feclora operation.

## Local service IPC foundation

`feclora.deployment.local_control` defines a bounded, length-prefixed JSON protocol
for a future persistent deployment service. It accepts only `status`, `arm`
and `cancel`; mutating requests must carry both a job UUID and an operator
confirmation. The Unix listener checks Linux peer credentials (UID 0 by
default), requires a root-owned non-writable parent directory, refuses to
replace an existing socket, and creates the socket with mode 0600. It does not
provide a shell or arbitrary method dispatch.

The primitive is now used by `feclora.deployment.service`, installed as
the non-boot-enabled systemd template `feclora-deployment@.service` and
controlled through the Cockpit API. A service instance loads one fresh,
verified job journal, validates the Server interface and restore image and its configured authenticity evidence,
owns a single-job lock, starts the existing TLS control listener and exposes
status/arm/cancel over the root-only socket. It can adopt the existing PXE
firewall zone on the same interface so the deployment TCP port is added and
removed without replacing PXE rules.

Cockpit can start/connect to the service, inspect live Client readiness, arm
with an exact job-specific phrase, cancel only before arming, and stop the
service only when no Client is actively writing. Unicast save/restore and
multicast restore use the existing control-plane execution methods; the daemon
does not duplicate the storage engines. The service is not enabled at boot,
supports one job per Server, and refuses to start from an interrupted journal.
A fresh definition is not considered interrupted until a service session has
started; a clean unarmed stop is restartable only when no Client session was
recorded. The listener's temporary firewall ownership and Unix-socket path are persisted/validated, and
systemd's `ExecStopPost` removes only stale root-owned socket/firewall artifacts after exit while
holding the single-service lock. No TLS session or storage operation is
resumed after a process crash. If the service exits during an armed/running
job, manual disk inspection and audit reconciliation are required. Automated
unit/CI checks do not establish real-network, VM or destructive storage
acceptance.

## Implemented and remaining

Implemented:
- TLS 1.3 mTLS context enforcement and exact peer identity verification;
- identity-to-MAC enrollment mapping and job allowlist enforcement;
- managed TCP listener start/stop lifecycle, pending-handshake cleanup, listener error reporting and interface-scoped firewalld port lifecycle;
- framed HELLO/JOB/READY/START/RESULT/CANCEL and transfer-offer/readiness messages;
- coordinator registration, readiness, explicit arming, running and per-client result transitions, one-client unicast orchestration and multi-client UDPcast whole-disk restore orchestration;
- private append-only SHA-256 hash-chained job journal; coordinator transitions are fsync-persisted before in-memory state changes, journal failures fail closed, verified journals can reconstruct the recorded coordinator/client state for audit, and interrupted jobs require explicit operator reconciliation. Reconstruction does not recreate TLS sessions, mark Clients READY, or resume storage work;
- mTLS-bound manifest transfer, optional minisign verification when a detached signature is present, exact artifact size/SHA-256 checks, private staging and no-overwrite publication;
- Client whole-disk save/restore callback integration with capture_disk and restore_disk, local typed confirmations, optional minisign verification/age decryption and destination read-back;
- Server runtime is now exposed through the persistent Cockpit service for unicast save/restore and multi-client multicast restore. Client runtime now has a read-only mTLS job-inspection handshake and a persistent Cockpit-driven unicast service. Cockpit selects the local disk/partition, displays the exact Server-bound confirmation phrase, and starts a non-boot-enabled Client unit. The service rechecks the live block-device inventory and root/mount safety before READY, then waits for the Server's explicit ARM before I/O. It records byte progress and terminal/interrupted status without automatic reconnect or resume. Cockpit Client multicast receive remains pending; the existing Client runtime still handles multicast restore.
- tests for framing, invalid messages, image transfer integrity, Client save/restore callbacks, scoped firewall lifecycle and a loopback TLS 1.3 client/server handshake using ephemeral test certificates.

Still required:
- automated integration tests that execute real capture/restore against disposable block devices over mTLS and UDPcast;
- automated PXE BIOS/UEFI VM boot, multi-client multicast execution, packet-loss/interrupt scenarios and full end-to-end acceptance. The libvirt harness and runbooks create/describe the lab; they do not execute the tests automatically or imply they passed;
- automated multicast network capability detection, per-client live progress, unicast multi-client fan-out, multicast save, CRL/OCSP integration, certificate/key provisioning and rotation on Client endpoints, and post-job power policies.
## PXE VM test lab

See [tests/vm/README.md](../tests/vm/README.md) and [run-pxe-matrix.sh](../tests/vm/run-pxe-matrix.sh). The lab uses an isolated libvirt network without libvirt DHCP so Feclora can be the only DHCP/PXE authority. Never use authoritative DHCP on a shared network.

## Optional cryptographic integrations and current gap

TLS certificates and mTLS endpoint authorization are core deployment security;
`age` and `minisign` are not substitutes for TLS and are not mandatory
installation dependencies. `age` is an optional image-confidentiality layer.
`minisign` is the current detached-manifest/profile signature implementation,
but the project requirement is to support an equivalent configured trust
mechanism without requiring that executable. Until the verifier abstraction
exists, document which existing deployment actions still depend on minisign
and do not claim those particular actions work when it is absent. SHA-256
alone detects corruption but cannot authenticate a publisher or prevent
malicious replacement.