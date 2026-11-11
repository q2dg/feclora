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

## Client identity provisioning

Unattended PXE uses a dedicated, per-Client removable identity medium. The
medium is prepared from an already enrolled Client in Cockpit using
**Export PXE mTLS identity**. It contains only that Client's CA certificate,
TLS certificate, TLS private key and (when configured) the Server's public
image-verification key. It does not contain image-signing or age private keys.

Use a separate ext4, XFS or Btrfs filesystem for each Client and label it
`FECLORA-CLIENT`. Keep the medium physically controlled: it is a bearer
credential for the Client's mTLS identity. Do not copy it into the Server's
shared TFTP/HTTP boot tree or distribute one Client's medium to another
machine. If it is lost, revoke that Client certificate in the Server trust
inventory and issue a new enrollment.

The Live image installs a read-only mount unit for that label at
`/mnt/feclora-pxe-identity` and a PXE-specific Client service template. The
template reads
`/mnt/feclora-pxe-identity/feclora-client-identity/deployment-client.json`
through the `FECLORA_CLIENT_CONFIG` override. The standard interactive
Client configuration path remains unchanged. The medium must be present and
readable before the PXE Client service starts; absent or invalid media fails
closed. The export operation refuses filesystems that cannot preserve POSIX
ownership and private-key permissions.

This resolves how the enrolled mTLS identity is made available to a fresh
Live PXE session without transmitting it over the network. It does **not**
yet start the Client automatically or authorize a restore. The job UUID and
Server endpoint remain public handoff metadata only. The remaining orchestration
must create a validated job request, resolve exactly one target from the
Server's stable WWN/serial binding, complete local preflight, and retain the
existing Server-side READY/ARM gate before any write.


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
