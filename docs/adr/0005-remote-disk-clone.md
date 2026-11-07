# ADR 0005: Authenticated one-to-one remote disk cloning

- Status: Accepted
- Date: 2026-11-08
- Scope: Direct disk-to-disk cloning between two independently operated feclora machines

## Context

A remote clone is a one-to-one operation: one source machine streams one physical
disk to one explicitly selected receiver machine and target disk. It is not a
repository upload, an SSH file copy, or a PXE/multicast deployment job.

The workflow must provide mutual TLS, explicit authorization by both endpoints,
bounded-memory transfer, end-to-end integrity, and read-back verification of
the receiver's destination disk. A successful TLS session alone is not
authorization to read or erase a disk.

## Decision

### Connection and identity

- The receiver initiates a TLS 1.3 connection to the source listener.
- Both peers validate the other certificate against an explicitly selected CA
  trust anchor and verify the expected peer identity (exact certificate SAN or
  an additional SHA-256 certificate fingerprint pin).
- Both peers require an explicit local authorization decision for the session.
  The source operator authorizes the exact source device and receiver identity;
  the receiver operator authorizes the exact source identity and destructive
  target device.
- Authorization is bound to a fresh session identifier, the two peer
  identities, source/target roles, device paths, and source geometry. It cannot
  be reused for another session or target.
- No password-only, unauthenticated, or opportunistic TLS mode is permitted.
  No automatic acceptance based only on a MAC address, IP address, or
  self-presented certificate is permitted.

### Transfer contract

- Exchange a strictly validated, versioned, length-bounded JSON session header
  before any target write. Reject unknown required semantics, oversized
  metadata, invalid geometry, and mismatched session/role identities and both
  device paths.
- The receiver sends a session-bound READY frame only after its own operator
  authorization, independently selected target-path match, capacity check and
  destructive-safety checks. The source must receive READY before starting dd
  or disclosing source disk data.
- Stream exactly the declared source byte count in fixed-size bounded chunks.
  Never buffer a complete disk image in memory.
- Compute SHA-256 over the source stream and receiver stream. Compare the
  sender's final digest with the receiver's in-flight digest. The stream
  terminal frame is bound to the session UUID.
- Write only to a receiver block device that has passed the local destructive
  target safety gate and exact typed confirmation.
- After the stream completes and the transfer digest matches, read the
  receiver disk back and calculate SHA-256 over the exact transferred byte
  count. Declare success only when the read-back digest matches.
- Report partial/failed status if transfer, digest comparison, flush, or
  read-back verification fails. A failed session may leave the receiver disk
  partially or fully overwritten; the UI must state this explicitly.

### Process and safety boundaries

- Use Python's standard ssl module for TLS and generic dd/block-device
  primitives for disk I/O. Do not use SSH/SFTP as the disk data plane.
- Keep network framing and transport separate from storage writers and device
  safety validation.
- Enforce socket read/write timeouts, maximum frame sizes, fixed chunk sizes,
  exact byte counts, and cancellation/connection-loss handling.
- Revalidate source and receiver device identity and safety immediately before
  the destructive transfer.
- Do not start the receiver writer until TLS identity checks, both explicit
  authorizations, session binding, metadata validation, and receiver target
  confirmation have completed.
- Do not report success from sender exit status or successful socket shutdown;
  receiver read-back verification is mandatory and its digest is returned in a
  session-bound receiver verification acknowledgement.
- This protocol is not the Server/Client PXE deployment protocol and does not
  provide multicast fan-out.

## Consequences

- Mutual TLS establishes peer identity; explicit per-session device
  authorization establishes permission. Both are required.
- Source pre-hashing is not required for transport correctness because the
  receiver verifies the sender's final stream digest and independently reads
  the target back. A mismatch is still a destructive failure and can leave a
  partial target.
- The source must remain stable and read-only for the duration of the stream.
  The implementation must reject mounted, busy, active-swap, or root-backed
  source devices and revalidate before reading.
- The initial runtime persists a per-endpoint operation start and terminal
  completed/failed/cancelled event in the existing append-only operation
  journal. More granular authorization/transfer phase events remain future
  work.
- The initial Python runtime now implements TLS socket helpers, local
  authorization gates, dd-based source/receiver streaming and receiver
  read-back acknowledgement. It is not yet a complete interactive feature:
  persistent journal integration, listener lifecycle, packaged-ISO wiring,
  and physical-device end-to-end validation remain outstanding.
