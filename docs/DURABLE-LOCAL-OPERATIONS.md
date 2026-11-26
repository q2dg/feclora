# Long-running local storage operations

The unprivileged GTK interface sends bounded JSON requests to the
root-owned, allowlisted helper. The helper validates parameters and submits
long-running local disk and partition operations to a durable queue executed
by a root-owned systemd worker. The UI process can exit without terminating an
accepted operation. Here, durable means independent of the UI and worker
process lifetime while the Live session's filesystem remains available; it
does not mean persistent across a Live reboot.

## Lifecycle

1. The privileged helper validates the action against its fixed allowlist.
   The backend validates the operation schema and writes a versioned immutable
   definition below `/var/lib/feclora/local-operations`.
2. The append-only JSONL event journal records `queued`. Each event includes
   a monotonically increasing sequence, previous-event hash and SHA-256 event
   hash. Files and directories are private to root.
3. `feclora-local-operation@.service` loads the definition in a process
   independent of the GTK interface.
4. The worker acquires the existing host-wide deployment/storage lock, then
   exclusive locks keyed by resolved block-device major/minor identity. This
   also prevents aliases such as a device node and its by-id symlink from
   bypassing the same-device exclusion.
5. The storage engine performs its own preflight, repository and
   destructive-confirmation checks before I/O. Progress and terminal state
   are appended to the journal. Each valid byte-progress checkpoint records
   monotonic elapsed time; sampled bytes/second is persisted only when two
   consecutive counters are comparable and time advanced.
6. The GTK interface requests operation status and recent journal events
   through the privileged helper.

## Recovery and cancellation

The `feclora-local-operation-recovery.service` classifies unfinished
operation definitions as `interrupted` when the state directory is present at
boot (for example, in an environment that explicitly preserves that state).
The default Feclora Live root is ephemeral: `/var/lib/feclora/local-operations`
is lost on reboot, so the appliance does not promise to recover its previous
session's queue or journal after a reboot. A reboot or power loss during a
write may leave the target partially modified without a surviving journal;
inspect that device before reuse. Recovery never replays a job or resumes
block-device writes.

The interface can request cancellation for queued, preflight and running
operations. A queued job is atomically marked `cancelled` before its worker
starts. For an active job, the backend asks systemd to stop its template unit.
The worker converts SIGTERM into an orderly cancellation exception, allowing
storage-engine cleanup to run. Direct child processes are terminated, given a
short grace period, and killed/reaped if they do not exit.

Cancellation is not rollback. A running restore or clone can leave its target
partially written; the journal sets `destination_may_be_partial` and the
interface warns the operator to inspect that device before reusing it.
Verification and terminal phases are not cancellable. A forced kill, power
loss or failed cleanup is recorded as interrupted/failed and still requires
manual inspection.

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
unit tests and static checks. Hardware behavior, service recovery and real
block-device safety still require operator acceptance. Reboot persistence is
not a requirement for the default Live appliance.
