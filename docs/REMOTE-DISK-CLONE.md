# One-to-one remote disk and partition cloning

Feclora implements direct whole-disk and partition-to-partition cloning as distinct clone-operation target types
inside the persistent Server/Client deployment lifecycle. The Server is the
source and the Client is the receiver. No second daemon, listener, IPC
protocol or job journal is created.

The clone stream reuses the existing Server-authenticated TLS control socket
after START. TLS authenticates the Server certificate to the Client only. The
Client does not present a certificate and is not individually authenticated
by the Server. The job UUID correlates the session; the selected Client MAC
scopes it to the job but is not a credential.

## Network preparation

On both machines, configure an active IPv4 interface/address using Cockpit's
Network tab. The Server job stores the selected Linux interface. The Client
operator selects a local IPv4 interface/address and uses Test connectivity
and inspect job. Feclora checks the route and binds the TCP connection to the
selected source address. The Client validates the Server certificate
chain and configured Server identity before displaying the job.

This preflight verifies the kernel's current route decision; it does not pin a
route against later network changes. A saved job definition does not prove
that a Client is online or reachable.

## Roles and local approvals

- Server/source: selects a whole disk or partition already marked read-only and types
  READ /dev/SOURCE.
- Client/receiver: selects its destination disk or partition locally and types
  ERASE /dev/DEVICE before READY.
- Server operator: explicitly arms the job after the Client is READY.

The Client's destination path is sent to the Server because the source and
receiver must agree on the clone target. This is not Client authentication.
The receiver independently revalidates its block-device identity, capacity,
logical sector size, writable status and destructive safety immediately
before writing. A smaller target is rejected.

## Source precondition

The selected source disk or partition must already report RO=1 in lsblk. The runtime never
changes a source disk's write-protection state automatically. An operator may
use a hardware write blocker or deliberately mark an offline source read-only
with blockdev --setro /dev/DEVICE; keep it read-only for the entire session.
Do not mark the running system disk read-only. Job creation and runtime both
check the source device.

## Session sequence

1. The Server operator creates a unicast clone job, selects the device type (disk
   or partition), chooses a matching read-only source device and selects the
   receiver MAC for this job.
2. The Client verifies the Server certificate, inspects the job, selects a
   local whole-disk destination and types the exact destructive confirmation.
3. The Server records READY. The operator explicitly arms the job.
4. The Server creates a fresh session UUID and source geometry. Protocol v2
   binds the device type (`disk` or `partition`) into the session header. The
   receiver independently checks that its selected target has the same type,
   sufficient capacity, matching logical sector size and writable/safe state.
5. The source streams exactly the declared number of bytes. The receiver
   writes incrementally while calculating SHA-256. Memory use is bounded by
   the configured chunk size and TLS/socket buffers.
6. The source waits for its reader to exit successfully, then sends a terminal
   frame containing the byte count and SHA-256. The receiver compares both
   values with its in-flight count and digest.
7. The receiver flushes the target and reads back the transferred byte count.
   It calculates a second SHA-256 and compares it with the transfer digest.
   For whole-disk clones only, a larger GPT target receives backup-header
   relocation and partition-table validation. Partition clones copy exactly
   the source partition length; any extra bytes at the end of a larger target
   partition are left unchanged and no partition-table repair is attempted.
8. The receiver records its durable operation result and reports the terminal
   result through the deployment control protocol. The Server records it in
   the deployment job journal.

## Required protocol properties

- TLS with Server certificate validation by the Client; no Client
  certificate or client authentication.
- Explicit local source and receiver device approvals.
- Fresh session UUID for correlation, not authentication.
- Strict bounded header and terminal-frame sizes; reject duplicate or unknown
  security-critical fields.
- Bounded streaming (64 KiB–4 MiB chunks), exact byte counts, SHA-256 and
  independent receiver read-back.
- Revalidate block-device identity immediately before writing and verification.
- Fail closed on disconnect, timeout, digest mismatch, device identity change,
  short write, reader error, flush error or read-back mismatch.
- Durable operation events on both endpoints and the persistent Server job
  journal.

## Failure semantics

Once the receiver writer starts, disconnects, timeouts or integrity failures
can leave the destination partially or fully overwritten. These are failures,
not rollbacks. The receiver must report the target as untrusted until a
subsequent successful restore or clone completes and verifies. Interrupted
jobs are never resumed automatically; inspect both endpoints and their
journals before starting another operation.

## Implementation boundaries

- DeploymentJob validates the clone operation, source device type, source path, unicast
  transport and absence of an image identifier.
- DeploymentControlServer and join_deployment reuse the persistent
  Server-authenticated TLS session and READY/START/result lifecycle.
- DeploymentService owns the managed worker, local IPC, job journal and
  explicit source-side ARM authorization.
- ClientDeploymentService owns local target selection, safety checks,
  explicit receiver authorization, progress and terminal status.
- The remote clone engine provides bounded disk/partition streaming, SHA-256
  validation and receiver read-back; GPT relocation is restricted to whole-disk
  clones.

Physical two-machine tests and hardware-specific validation remain operator
acceptance activities; CI does not imply they have passed.
