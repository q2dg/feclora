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
   revalidates its target identity, capacity, read-only status and destructive
   safety. No writer starts before both endpoints have passed these gates.
5. The source streams exactly the declared number of bytes. The receiver
   writes incrementally to the target while calculating SHA-256. Memory use is
   bounded by the configured chunk size and TLS/socket buffers.
6. The source sends a terminal frame containing the byte count and SHA-256.
   The receiver compares both values with its in-flight count and digest.
7. The receiver flushes the target and reads back exactly the transferred byte
   count. It calculates a second SHA-256 and compares it with the transfer
   digest.
8. The receiver returns a terminal verification result bound to the session
   UUID, including the read-back digest. Only a successful receiver read-back
   verification is reported as success. Both endpoints journal the outcome.

## Required protocol properties

- TLS 1.3 with client-certificate authentication in both directions.
- Explicit expected peer identity checks (SAN identity or pinned fingerprint).
- Explicit local authorization on both endpoints; mTLS is not an authorization
  substitute.
- Fresh, non-reusable session UUID and role-bound authorization, including
  exact source and receiver device paths.
- Strict maximum header and terminal-frame sizes; reject duplicate or unknown
  security-critical fields.
- Fixed-size bounded streaming, exact byte counts, timeouts and cancellation.
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
transport. Generic block tools such as dd, plus feclora's existing device
inventory, safety gates, progress handling and operation journal, provide the
storage behavior. The protocol does not transfer image files, invoke SSH/SFTP,
or reuse the multicast deployment coordinator.

The implementation is planned; this document is a protocol specification, not
a claim of working remote clone functionality.
