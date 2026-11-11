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
signed per-Client profile. The operator still selects the local /dev target
and types the local confirmation in Cockpit. No profile expiry, nonce/replay
ledger, automatic Client startup or write authorization is provided by this
binding alone. Existing jobs without target_bindings retain the interactive
workflow.

## Required authenticated flow

1. The Client boots the shared Live image and parses the unattended handoff.
2. A pre-enrolled Client identity establishes TLS 1.3 mutual authentication to
   the advertised Server control endpoint. MAC address, IP address and job
   UUID are not authentication credentials.
3. The Server verifies that the certificate identity is enrolled, not revoked,
   and explicitly authorized for this job.
4. The Client obtains a signed, immutable per-Client restore profile over the
   authenticated control channel. The profile binds the job UUID, Client
   certificate identity, image-manifest digest, expiry, single-use nonce and
   a stable target selector (WWN and/or serial). It must not select a disk by
   transient `/dev/sdX` name.
5. The Client verifies the profile signature against pinned Server trust,
   checks expiry and replay state, verifies the manifest and artifact digests,
   resolves exactly one target by WWN/serial, and runs all local restore
   preflights. It sends READY only after all checks pass.
6. The Server requires every expected Client to be authenticated and READY.
   No storage write begins until the Server operator explicitly ARMs the job.
7. The Client rechecks target identity immediately before writing, restores,
   performs read-back verification, and reports a terminal per-Client result.
   The Server persists the job/replay outcome and reconciles every Client.

## Credential provisioning constraint

The Live session is intentionally ephemeral. A PXE boot script, TFTP payload,
HTTP response, kernel command line, DHCP option or unauthenticated network
request must never carry a Client private key or reusable bootstrap secret.

Therefore unattended PXE requires a secure way to make the already-enrolled
Client mTLS identity available inside the fresh Live session. That provisioning
mechanism is not implemented yet and must be selected before Client auto-start
is enabled. Acceptable designs must bind the credential to the intended Client
and protect it at rest and in use (for example, a hardware-backed/TPM-sealed
identity or an explicitly provisioned secure local medium). MAC-only
enrollment, public boot parameters and shared fleet-wide secrets are not
acceptable substitutes.

Until that mechanism exists, the unattended boot script is only a safe
job-bound handoff. It must not start a writer or fall back to interactive
credentials silently.

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

- Select and implement secure per-Client credential provisioning into Live.
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
