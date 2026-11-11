# Unattended PXE restore design and implementation status

## Implemented boot handoff

Interactive and unattended boot use the same Fedora Live kernel, initramfs and
squashfs payload. The normal iPXE menu exposes both paths. The unattended path
chains to `unattended.ipxe`, which is published only while an active Server
restore job is running.

The job-bound script contains only:
- the public Server IPv4 address;
- the actual TLS control port returned by the Server listener;
- the non-secret deployment job UUID;
- the unattended boot-mode selector.

It contains no certificate, private key, password, enrollment token or restore
authorization. The Live command-line parser validates the UUID and endpoint,
but these values are only a handoff request. They do not authorize a write.
The Server publishes the script atomically, refuses to overwrite another
active job's script, revokes the matching script when the job UI exits, and a
new PXE session removes a safe stale script left by an interrupted Server
process.

## Implemented stable target-binding groundwork

Server restore-job creation can optionally bind each selected Client MAC to a
physical target WWN, serial number, or both. The binding is part of the
validated job document sent over the TLS 1.3 mTLS control session. The Client
compares every supplied identifier with its own current block-device inventory
before it reports READY; a missing or mismatching identifier rejects the
selection. The Server UI collects these values per selected Client, and the
job schema rejects selectors for non-authorized Clients, incomplete Client
coverage, empty selectors, non-restore/partition targets, unknown fields and
control characters.

This is a preflight constraint, not unattended target discovery or a
signed per-Client profile. WWN/serial matching reduces accidental
mis-targeting but is not cryptographic hardware attestation. The operator still selects the local /dev target
and types the local confirmation in Cockpit. No profile expiry, nonce/replay
ledger, automatic Client startup or write authorization is provided by this
binding alone. Existing jobs without target_bindings retain the interactive
workflow.

## Authenticated unattended flow

1. The Server publishes a job-bound iPXE script containing only the Server
   IPv4 address, control port and job UUID.
2. The Client boots the Live image. For unattended mode, systemd mounts the
   dedicated `FECLORA-CLIENT` identity medium read-only, validates its
   deployment configuration and automatically creates a private local job
   request. Interactive boots do not start this dispatcher.
3. The dispatcher starts the job-specific PXE Client service. The Client
   connects using TLS 1.3 mutual authentication and the identity on its
   removable medium. The Server checks the certificate against its enrollment
   and revocation state and checks that the enrolled identity is authorized
   for the requested job.
4. The unattended path currently accepts **unicast whole-disk restore only**.
   The job must bind this Client to a WWN and/or serial number. The Client
   resolves exactly one local whole disk using that selector, then rechecks
   the selected device, block-device status and source-safety conditions.
   Missing, mismatching or ambiguous selectors fail before READY.
5. The Client sends READY only after its local preflight succeeds. The Server
   still requires the operator's explicit ARM action before sending START.
6. The Client restores through the existing authenticated transfer path,
   performs the restore engine's integrity/read-back verification, and sends
   its terminal result to the Server.

The Server endpoint in the kernel command line is not trusted by itself: the
Client verifies the Server certificate identity against the pinned identity
from its enrollment configuration. The boot parameters never select a
`/dev` target and never authorize a write. No automatic resume or replay of
disk I/O is attempted after an interruption.


## Multi-Client and transport constraints

- Each Client receives its own profile and target selector, even when all
  Clients restore the same immutable image.
- A single Client may be targeted by one job at a time. Duplicate or replayed
  profile consumption is rejected by Server-side persistent state.
- Unicast and multicast share the same authenticated control plane and
  per-Client READY/ARM gate. Multicast changes only artifact data transport.
- UDPcast datagrams are not authenticated or encrypted by UDPcast itself;
  network isolation and optional artifact encryption remain separate controls.
- Partial failure is reported per Client. A failed receiver must not cause
  another Client's successful result to be overwritten or misreported.
- No automatic resume or replay of disk I/O occurs after reboot. Operators
  inspect interrupted targets before creating a new job.

## Remaining release-critical work

- Select and implement per-Client credential provisioning into the Live session without placing reusable credentials in network boot assets.
- Add automatic Client service startup for unattended boot.
- Add Server-to-Client signed profile delivery and certificate/job/profile
  binding.
- Extend the implemented optional job-level WWN/serial preflight binding into signed per-Client profile authoring and automatic unique target resolution.
- Integrate expiry, nonce/replay protection, manifest digest binding and
  Server-side single-use state.
- Add unattended local preflight, READY, ARM, progress, read-back verification
  and terminal result reconciliation.
- Validate BIOS and UEFI PXE, one Client and multiple Clients, unicast and
  multicast, missing credentials, revoked identities, expired/replayed
  profiles, ambiguous targets, target swaps and network interruption.
