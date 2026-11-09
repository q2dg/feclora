# One-to-one remote disk cloning

Feclora implements direct whole-disk cloning as a distinct `clone` operation
inside the existing persistent Server/Client deployment lifecycle. The Server
is the source and the Client is the receiver. This does not create a second
daemon, listener, IPC protocol, or job journal.

UDPcast is not the data plane for this operation. Feclora's UDPcast integration
transfers image artifact files into private staging before signed-image
multicast restore; it does not stream one block device directly into another.
Remote clone therefore reuses the existing bounded block-stream engine over
the already authenticated TLS 1.3 Client control socket after the job's START
frame. No additional network port or TLS service is opened.

## Roles and authorization

- **Server/source:** selects a whole disk already marked read-only.
- **Client/receiver:** selects its destination disk locally.
- **Operators:** independently approve the exact peer and local device.

Both endpoints reuse the enrolled TLS 1.3 mutual-authenticated control session
and existing exact peer-identity checks. The Client operator must type
`ERASE /dev/DEVICE FROM SERVER_IDENTITY` before reporting READY. For a clone
job, the Client includes the locally approved target path in its READY frame.
The Server binds that path, its configured source path, and both enrolled
certificate identities into the session header. The Client checks the header
against its local selection and repeats block-device safety checks before
writing.

The Server operator must type the exact job-specific phrase:

`ARM JOB_UUID AND READ /dev/SOURCE TO CLIENT_IDENTITY`

This approval binds the Server source disk to the enrolled receiver identity.
The READY target path is disclosed to the Server so the session header can
bind both endpoints; it is not treated as authorization by itself.

## Source precondition

The source disk must already report `RO=1` in `lsblk`. The runtime never
changes a source disk's write-protection state automatically. An operator may
use a hardware write blocker or deliberately mark an offline source read-only
with `blockdev --setro /dev/DEVICE`; keep it read-only for the entire session.
Do not mark the running system disk read-only. Job creation verifies that the
selected source is a whole disk, is currently read-only, and passes the
existing source-safety checks. The runtime rechecks it before streaming.

## Session sequence

1. The Server operator creates a unicast clone job, selects a read-only source
   disk, and authorizes exactly one enrolled Client.
2. The Client inspects the authenticated job, selects a local whole-disk
   destination, and types its exact destructive confirmation before READY.
   The Server records the Client's READY state through the existing coordinator.
3. The Server operator enters the job-specific ARM phrase above. The existing
   service validates the phrase and starts its managed worker; no new service
   or network listener is started.
4. The Server derives a fresh session UUID and source geometry, and binds the
   source/target paths and peer identities in a bounded session header. Both
   endpoints verify the peer identity and local device authorization.
5. The receiver independently revalidates its block-device identity,
   capacity (equal to or greater than the source), logical sector size,
   writable status and destructive safety. A smaller target is rejected
   before READY. The source waits for the receiver's session-bound READY
   frame before launching `dd` or disclosing disk data.
6. The source streams exactly the declared number of bytes. The receiver
   writes incrementally while calculating SHA-256. Memory use is bounded by
   the configured chunk size and TLS/socket buffers.
7. The source waits for its `dd` reader to exit successfully, then sends a
   terminal frame containing the byte count and SHA-256. The receiver compares
   both values with its in-flight count and digest.
8. The receiver flushes the target and reads back exactly the transferred byte
   count. It calculates a second SHA-256 and compares it with the transfer
   digest. If the target is larger and the copied table is GPT, it runs
   `sgdisk -e` to relocate the backup GPT header to the physical end of the
   target and `sgdisk -v` to validate the table. GPT relocation occurs only
   after the original source-sized range passes read-back verification.
   Immediately before that metadata write, the receiver revalidates target
   identity and repeats the mounted/in-use safety check. It repeats identity
   and safety checks after relocation before GPT verification.
9. The receiver returns a terminal verification result bound to the session
   UUID, including the read-back digest. The receiver's durable operation
   journal is completed before it acknowledges success. The Client then sends
   the terminal result through the existing deployment control protocol; the
   Server records the result in the existing deployment job journal.

## Required protocol properties

- TLS 1.3 with mandatory peer certificates and exact enrolled peer identity.
- Explicit local authorization on both endpoints; mTLS is not an authorization
  substitute.
- Fresh session UUID and role-bound authorization, including exact source and
  receiver device paths.
- Strict maximum header and terminal-frame sizes; reject duplicate or unknown
  security-critical fields.
- Bounded streaming (64 KiB–4 MiB chunks) and exact byte counts. Active
  disk writing is intentionally non-cancellable through the persistent
  workflow; graceful service shutdown waits for the worker to finish.
- SHA-256 over the source/receiver stream and independent receiver read-back.
- No path-based target acceptance alone: the receiver resolves and revalidates
  block-device identity immediately before writing and verification.
- Fail closed on disconnect, timeout, digest mismatch, device identity change,
  short write, `dd` error, flush error or read-back mismatch.
- Durable operation events on both endpoints and the persistent deployment
  job journal on the Server.

## Failure semantics

Once the receiver writer starts, disconnects, timeouts, or integrity failures
can leave the destination partially or fully overwritten. The persistent
workflow does not expose cancellation after ARM. A graceful service stop
waits for the active worker to finish; abrupt process/host failure or peer
disconnection can interrupt the underlying I/O. These are failures, not
rollbacks. The UI must not imply that the destination is restored to its
previous contents. The receiver must report the target as
untrusted until a subsequent successful restore or clone completes and
verifies. Interrupted jobs are never resumed automatically; inspect both
endpoints and their journals before starting another operation.

## Implementation boundaries

The integration reuses these existing components:

- `DeploymentJob` validates the `clone` operation, its source disk, unicast
  transport, and absence of an image identifier.
- `DeploymentControlServer` and `join_deployment()` reuse the persistent
  mTLS control session, READY/START handshake, peer enrollment and job state.
- `DeploymentService` owns the existing managed worker, local IPC, job journal,
  and explicit source-side ARM authorization.
- `ClientDeploymentService` owns local target selection, safety checks,
  explicit receiver authorization, progress and terminal status.
- `build_remote_clone_header()`, `send_remote_disk()`, and
  `receive_remote_disk()` provide the existing bounded block stream, `dd`
  I/O, SHA-256 stream validation, receiver read-back and GPT relocation.
- `Cockpit` exposes the clone job workflow without adding a parallel UI path.

The standalone `serve_remote_clone_once()` and `connect_remote_clone()`
helpers remain available for isolated integrations and tests; the persistent
Feclora job path does not use them because it already owns an authenticated
control socket.

The Python unit tests and CI cover the job contract, local approvals, the
existing clone engine and integration plumbing. Physical two-machine tests
and hardware-specific validation are operator acceptance activities described
in [ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md). Automated fault-injection coverage
for established socket disconnects and interrupted journal recovery is a
software test responsibility.
