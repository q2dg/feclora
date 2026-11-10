# Durable local storage operations

Cockpit remains the operator interface, but long-running local disk and
partition operations are accepted into a durable queue and executed by a
root-owned systemd worker. The HTTP/Cockpit request only validates and
persists the request, asks systemd to start its job unit, and returns the
operation identifier.

## Lifecycle

1. The Cockpit API validates the allowlisted operation and its parameter
   schema, then writes a versioned immutable definition below
   `/var/lib/feclora/local-operations`.
2. The append-only JSONL event journal records `queued`. Each event includes
   a monotonically increasing sequence, previous-event hash and SHA-256 event
   hash. Files and directories are private to root.
3. `feclora-local-operation@.service` loads the definition in a process
   independent of Cockpit, the browser and HTTP request lifetime.
4. The worker acquires the existing host-wide deployment/storage lock, then
   exclusive locks keyed by resolved block-device major/minor identity. This
   also prevents aliases such as a device node and its by-id symlink from
   bypassing the same-device exclusion.
5. The existing storage engine performs its own preflight, repository and
   destructive-confirmation checks before I/O. Progress and terminal state
   are appended to the durable journal.
6. Cockpit polls `local_operation_status`; `local_operations` returns
   recent operation summaries and their event history.

## Recovery and cancellation

The boot-time `feclora-local-operation-recovery.service` runs before the
Cockpit socket and enumerates every persisted operation definition, not just
the most recent history page. It marks every unfinished queued/preflight/
running/verifying operation as `interrupted`. A damaged journal is reported
for manual inspection without preventing recovery of other jobs. Recovery
never replays a job or resumes block-device writes.

Cockpit can request cancellation for queued, preflight and running operations.
A queued job is atomically marked `cancelled` before its worker starts. For an
active job, Cockpit asks systemd to stop its template unit. The worker converts
SIGTERM into an orderly cancellation exception, allowing storage-engine
cleanup to run. Direct child processes are terminated, given a short grace
period, and killed/reaped if they do not exit. If a storage operation is
waiting on a separate transient SFTP unit, the worker waits for that unit to
stop before removing its local staging files.

Cancellation is not rollback. A running restore or clone can leave its target
partially written; the journal sets `destination_may_be_partial` and Cockpit
warns the operator to inspect that device before reusing it. Verification and
terminal phases are not cancellable. A forced kill, power loss or failed
cleanup is recorded as interrupted/failed and still requires manual inspection.

## State model

- `queued` -> `preflight` -> `running` -> `verifying` -> `completed`
- `queued`, `preflight` and `running` may instead end in `cancelled`.
- `queued`, `preflight`, `running` and `verifying` may end in `failed`
  or `interrupted` where applicable.
- `progress` events are append-only checkpoints while the logical state
  remains `running`; they do not change the state machine.

## Operational limits

This implementation does not create an ISO and does not depend on a VM or
physical-disk acceptance run. Its automated coverage is limited to focused
unit tests and static checks. Hardware behavior, boot-time systemd ordering,
Cockpit disconnect behavior on a live system, and real block-device safety
still require a separately planned operator acceptance exercise.
