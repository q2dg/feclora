# One-to-one remote disk cloning

This document specifies direct disk-to-disk cloning between two feclora
machines. It is deliberately separate from PXE boot, Server/Client deployment
jobs, and multicast distribution.

## Roles

- **Source:** owns the disk being read and exposes a short-lived TLS listener.
- **Receiver:** initiates the connection and owns the destination disk.
- **Operator on each endpoint:** explicitly authorizes the exact peer and local
  device involved in the session.

The receiver initiates the connection. Both endpoints authenticate the other
using TLS 1.3 and a configured trust anchor or pinned certificate fingerprint.
Each endpoint also checks the expected peer identity; certificate validation
without identity matching is insufficient.

## Session sequence

1. Both operators configure the expected peer identity and approve the
   one-to-one session. The source approval names the source disk and receiver
   identity. The receiver approval names the source identity and destination
   disk and requires the exact destructive phrase ERASE /dev/DEVICE.
2. The receiver connects to the source using mutual TLS. Neither endpoint
   accepts an untrusted, mismatched, expired, or wrong-role peer certificate.
3. The peers exchange a versioned, bounded session header containing a fresh
   session UUID, endpoint roles and identities, source byte count, logical
   sector size, and a fixed transfer chunk size. The receiver rejects a header
   that does not match its independently approved session.
4. The source revalidates its device identity and read safety. The receiver
   revalidates its target identity, exact capacity, logical sector size,
   read-only status and destructive safety. Protocol v1 currently requires
   equal source/target capacities so the full transferred extent can be
   compared byte-for-byte without relocating GPT metadata.
5. The source streams exactly the declared number of bytes. The receiver
   writes incrementally to the target while calculating SHA-256. Memory use is
   bounded by the configured chunk size and TLS/socket buffers.
6. The source waits for its dd reader to exit successfully, then sends a
   terminal frame containing the byte count and SHA-256. The receiver compares
   both values with its in-flight count and digest.
7. The receiver flushes the target and reads back exactly the transferred byte
   count. It calculates a second SHA-256 and compares it with the transfer
   digest.
8. The receiver returns a terminal verification result bound to the session
   UUID, including the read-back digest. Only a successful receiver read-back
   verification is reported as success. Both endpoints persist started and
   terminal completed/failed/cancelled operation events before reporting
   completion to their caller.

## Required protocol properties

- TLS 1.3 with client-certificate authentication in both directions.
- Explicit expected peer identity checks (SAN identity or pinned fingerprint).
- Explicit local authorization on both endpoints; mTLS is not an authorization
  substitute.
- Fresh, non-reusable session UUID and role-bound authorization, including
  exact source and receiver device paths.
- Strict maximum header and terminal-frame sizes; reject duplicate or unknown
  security-critical fields.
- Bounded streaming (64 KiB–4 MiB chunks), exact byte counts and cancellation.
  TLS helpers apply a 15-second client connection timeout and a 120-second
  socket I/O timeout; the caller may choose stricter values.
- SHA-256 over source/receiver stream and independent receiver read-back.
- No path-based target acceptance alone: the receiver resolves and revalidates
  the block-device identity immediately before writing and verification.
- Fail closed on disconnect, timeout, digest mismatch, device identity change,
  short write, dd error, flush error or read-back mismatch.
- Record operation IDs and terminal outcomes in the persistent journal.

## Failure semantics

Once the receiver writer starts, cancellation, disconnect, or any integrity
failure can leave the destination partially or fully overwritten. The UI must
not imply rollback. The receiver must report the target as untrusted until a
subsequent successful restore or clone completes and verifies.

## Implementation boundaries

Python's standard ssl and socket facilities provide the authenticated
transport. The initial runtime is in
`src/feclora/network/remote_clone.py`:

- `send_remote_disk()` runs on the source endpoint after the receiver has
  connected over mTLS. It validates and reads the source with `lsblk` and
  `dd`, then waits for the receiver's verification acknowledgement.
- `receive_remote_disk()` runs on the receiver endpoint. It validates the
  target, writes through `dd`, reads back the complete source-sized extent,
  and sends a success acknowledgement only when SHA-256 matches.
- `serve_remote_clone_once()` accepts one connection as the source, while
  `connect_remote_clone()` connects as the receiver and owns the TLS socket
  lifecycle for that session.
- `src/feclora/network/tls.py` provides the client/server TLS socket wrappers.
  The caller still owns listener creation, certificate provisioning and UI
  authorization prompts. The TLS helpers apply bounded connection/I/O
  timeouts. The runtime writes to the persistent operation journal by
  default; callers can
  override its path for isolated deployments and tests.

The implementation does not transfer image files, invoke SSH/SFTP, or reuse
the multicast deployment coordinator. It is an initial runtime foundation,
not yet a production-ready interactive feature: end-to-end TLS hardware tests,
interactive cancellation UI and broader recovery tests remain outstanding.
