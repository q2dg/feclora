# ADR 0010: Durable local storage operations independent of the UI

- Status: Accepted
- Date: 2026-11-09
- Scope: local disk/partition capture, restore, extraction and cloning

## Context

Local storage operations are currently dispatched by the Cockpit-facing Python
API. Their operation log is durable and records progress, and interrupted
originating processes can be identified for manual review. However, the
storage engine still runs in the API/request process. A browser disconnect,
Cockpit/API restart or request lifecycle failure can therefore interrupt work.

The repository also contains a historical `dialog` prototype. That prototype
invokes storage engines directly from its own process and uses the lifetime of
a `dialog --gauge` subprocess to report progress. It is not a durable worker
and must not be re-enabled as a workaround for the Cockpit request lifecycle.
Switching that same execution model to `dialog` or `zenity` would move, not
solve, the lifecycle problem.

## Decision

Keep Cockpit as the primary operator interface. Do not replace it with
`dialog` or `zenity` as part of the durable-operations work.

Move local long-running storage execution behind a root-owned service boundary
whose lifetime is independent of Cockpit, HTTP requests, browser tabs and
terminal sessions. The UI submits a validated operation request and receives
a durable operation identifier; it then reads status, progress and history
through a narrow privileged API. Disconnecting the UI must not stop a job.

The service must:

- Persist a versioned operation definition and append-only state/progress
  events under root-owned protected storage.
- Enforce a single authoritative state machine, including queued, preflight,
  running, verifying, completed, failed, cancelled and interrupted states.
- Serialize conflicting operations with process-independent locks, including
  per-device conflict detection and the existing host-wide storage/deployment
  exclusion rules.
- Revalidate device identity, repository identity, destructive confirmation
  and authorization immediately before execution; a queued request is not
  durable authorization to overwrite a device.
- Record progress and terminal outcomes durably, with bounded diagnostic
  information and no secrets.
- Treat service restart during destructive I/O as interruption. Never replay or
  automatically resume a write to a block device. Require inspection and a new
  explicitly authorized operation.
- Allow an operator to request cancellation while a worker is in preflight or running.
  The worker handles systemd SIGTERM, lets its storage engine unwind, and bounds
  child-process shutdown with terminate-then-kill. Cancellation is not rollback:
  a running restore or clone may leave its destination partially written, which
  must be inspected before reuse. Verification and terminal phases are not cancellable.
- Expose only bounded, allowlisted operations over the existing privileged
  Cockpit/API boundary and a root-owned local IPC mechanism. Do not expose a
  shell, arbitrary executable, arbitrary argv or filesystem path API.

Reuse the storage-safety checks, host-wide exclusion and audit principles
already present in the Server deployment service. Do not create a parallel
deployment daemon or a second host-wide lock. Local jobs currently use their
own versioned, hash-chained journal and per-device lock files; they do not
silently reinterpret or rewrite existing deployment journals.

## Interface consequences

Cockpit remains the supported primary interface and becomes a client of the
durable local operation service. Its request handlers must return promptly
after acceptance and expose operation ID, status, event history and progress.

A console interface may be reconsidered later as an additional client of the
same service. If added, `dialog` is the more suitable candidate for a
headless/local rescue console; `zenity` is only appropriate when a graphical
desktop session is an explicit product requirement. Neither interface may
invoke storage engines directly or own the lifetime of a destructive job.

The existing `src/feclora/ui/dialog_app.py` is a legacy prototype, not a
supported alternate backend or proof that a console migration is complete.
It must not be wired into the Live startup flow until it has been refactored
to submit and monitor durable service jobs and to use the same authorization,
repository, device-lock and audit contracts as Cockpit.

## Implementation status

The implementation is present on `main`: Cockpit submits validated,
allowlisted operation definitions to a root-owned queue; a systemd template
unit executes each job independently of the request process; a hash-chained
event journal records state and byte progress; and the worker reuses the
host-wide storage lock plus per-block-device locks. This state survives browser,
Cockpit/API and worker-process lifetimes while the current filesystem remains
available. The default Live root is ephemeral, so the queue and journal are
lost on reboot; reboot persistence is not a product requirement. The recovery
unit can classify unfinished records as interrupted only when those records
are present at boot. No destructive I/O is replayed.

The implementation deliberately uses systemd activation and a file-backed
handoff rather than the originally considered dedicated local IPC service.
Remaining work includes consistent phase/throughput telemetry, history export,
stronger detached-worker supervision, and live systemd/Cockpit acceptance.
The latter is not claimed by unit tests or static checks.

## Acceptance

- Closing a browser tab or restarting Cockpit does not terminate an accepted
  local operation.
- Operation state and progress remain queryable after Cockpit/API or worker-process restart within the same Live session.
- A worker/service crash during a write leaves an interrupted record while the
  session filesystem survives; after Live reboot the operator must assume the
  target may be partial and inspect it. No block-device I/O is resumed automatically.
- Two operations that target the same device cannot execute concurrently,
  including when submitted through different UI clients.
- All destructive actions are revalidated by the service immediately before
  execution and retain typed confirmation and authorization requirements.
- Unit tests cover state transitions, persistence, restart recovery, lock
  contention, duplicate submissions, journal integrity, cancellation boundaries
  and bounded child-process shutdown.
- No ISO build, VM lab or physical-disk test is implied by this software design
  decision; operator acceptance remains separately documented.


## Cancellation semantics

Cockpit can cancel queued, preflight and running local operations. A queued job
is marked cancelled in its journal before its worker starts. For an active job,
Cockpit asks systemd to stop the template unit; the worker translates SIGTERM
into a cancellation exception so Python cleanup paths run. Storage subprocesses
are terminated, given a short grace period, and killed/reaped if they do not
exit. systemd retains a final timeout as a hard-stop boundary. The journal
records the cancellation reason and whether a running restore/clone may have
partially modified its destination. A cancelled destination is never treated
as rolled back or safe to reuse without inspection.
