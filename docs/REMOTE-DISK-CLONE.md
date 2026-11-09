# One-to-one remote disk cloning

Feclora implements direct whole-disk cloning as a distinct `clone`
operation inside the existing persistent Server/Client deployment lifecycle.
It does not create a second daemon, listener, IPC protocol, or job journal.
The Server is the source and the Client is the receiver.

The current UDPcast integration is not the data plane for this operation:
UDPcast transfers image artifact files into private staging before signed-image
restore; it does not stream a source block device directly into a receiver
block device. Clone therefore reuses Feclora's existing bounded block-stream
engine and runs it over the already authenticated TLS 1.3 control socket after
the job's START frame. No additional network port or TLS service is opened.

## Roles

- **Source:** the Server owns the read-only source disk.
- **Receiver:** the Client owns the destination disk and selects it locally.
- **Operator on each endpoint:** explicitly authorizes the exact peer and local
  device involved in the session.

Both endpoints reuse the TLS 1.3 mutual-authenticated control session and the
existing enrolled peer identity checks. The Server operator confirms the
source disk and enrolled Client identity as part of the job-specific ARM
phrase. The Client operator separately types the destructive confirmation for
its selected destination. CA validation without exact peer identity matching
is insufficient.

## Source precondition

The source disk must already report `RO=1` in `lsblk`. The runtime never
changes a source disk's write-protection state automatically. An operator may
use a hardware write blocker or deliberately mark an offline source read-only
with `blockdev --setro /dev/DEVICE`; keep it read-only for the entire session.
Do not mark the running system disk read-only.

## Session sequence

1. The Server operator creates a unicast clone job, selects a whole source
   disk already marked read-only, and authorizes exactly one enrolled Client.
   The Client inspects the authenticated job, selects its own destination disk,
   and types `ERASE /dev/DEVICE FROM SERVER_IDENTITY` before reporting READY.
2. The Client sends its approved target path in the clone-specific READY frame.
   The Server binds that path, its configured source path, and both enrolled
   certificate identities into a fresh session header. The Client checks that
   the header names the same locally selected target; it still performs its
   own block-device identity and safety checks before writing.
3. The Server operator must type the exact job-specific phrase
   `ARM JOB_UUID AND READ /dev/SOURCE TO CLIENT_IDENTITY`. The Server checks
   that the source is still read-only before sending START. The existing mTLS
   session is then used for the bounded clone protocol; no new connection is
   opened.
4. Each endpoint verifies the peer identity again. The source revalidates its
   device identity and read safety. The receiver revalidates its target
   identity, capacity (equal to or greater than the source), logical sector
   size, writable status and destructive safety. A smaller target is rejected
   before READY. The receiver writes and verifies exactly the source-sized
   byte range; extra destination capacity is not part of the transfer digest.
5. Only after the receiver has completed its local authorization and target
   safety checks does it send a session-bound READY frame. The source waits for
   that frame before launching dd or disclosing disk data.
6. The source streams exactly the declared number of bytes. The receiver
   writes incrementally to the target while calculating SHA-256. Memory use is
   bounded by the configured chunk size and TLS/socket buffers.
7. The source waits for its dd reader to exit successfully, then sends a
   terminal frame containing the byte count and SHA-256. The receiver compares
   both values with its in-flight count and digest.
8. The receiver flushes the target and reads back exactly the transferred byte
   count. It calculates a second SHA-256 and compares it with the transfer
   digest. If the target is larger and the copied table is GPT, it then runs
   `sgdisk -e` to relocate the backup GPT header to the physical end of the
   target and `sgdisk -v` to validate the table. GPT relocation occurs only
   after the original source-sized range has passed read-back verification.
   Immediately before that metadata write, the receiver revalidates the target
   block-device identity, repeats the mounted/in-use safety check and honors an
   operator cancellation request. It repeats the identity and safety checks
   after relocation before running GPT verification; if the target becomes
   mounted or otherwise unsafe, the operation fails closed and is not reported
   as verified.
9. The receiver returns a terminal verification result bound to the session
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
  TLS helpers apply a 15-second client connection deadline, polling TCP
  connection attempts at a bounded interval so the caller's cancellation
  callback is observed during connect, and a 120-second socket I/O timeout.
  Cancellation is not yet interruptible during every blocked TLS handshake or
  established-socket I/O operation.
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

- `build_remote_clone_header()` creates a fresh session UUID and derives the
  source byte count and logical sector size from `lsblk`; it refuses a source
  that is not already marked read-only.
- `send_remote_disk()` runs on the source endpoint after the receiver has
  connected over mTLS. It validates and reads the source with `lsblk` and
  `dd`, waits for the receiver READY frame, then waits for the final
  verification acknowledgement.
- `receive_remote_disk()` runs on the receiver endpoint. It validates the
  target, writes through `dd`, reads back the complete source-sized extent,
  and sends a success acknowledgement only when SHA-256 matches.
- `serve_remote_clone_once()` accepts one connection as the source, polls its
  listening socket at a bounded interval, and honors the caller's cancellation
  callback while waiting for the receiver. It restores the listener's original
  timeout after the attempt. Once connected, the same cancellation callback is
  passed into the disk sender. `connect_remote_clone()` connects as the receiver
  and owns the TLS socket lifecycle for that session. The receiver's TCP
  connect phase polls cancellation between bounded connection attempts and
  stops before TLS negotiation if cancellation is requested.
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
