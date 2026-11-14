# Deployment coordinator

`feclora.deployment.coordinator.DeploymentCoordinator` is the in-process
state machine used by the persistent Server deployment service and its
Server-authenticated control protocol.

## Lifecycle

- Job: `created -> armed -> running -> completed|failed`; cancellation is
  terminal.
- Client: `connected -> ready -> running -> succeeded|failed`, or
  `connected|ready|running -> disconnected`.
- New clients cannot join after the job is armed.
- A client must be in the job's MAC allowlist and the caller must report that
  its control channel has already authenticated it.
- Manual start requires at least one ready client and an explicit `arm()`.
- Expected-client start requires the configured number of ready clients.
- Deadline start requires at least one ready client and the UTC deadline to
  have elapsed; the operator still explicitly calls `arm()`.
- Per-client results determine the final job result. A failed or disconnected
  client prevents the job from being reported as fully successful.

## Security and scope

The `authenticated=True` argument is an integration boundary, not an
authentication mechanism. In the current deployment it represents the
Server-authenticated TLS control session; it does not mean the Server has
cryptographically authenticated the Client. MAC addresses are operational
job selectors, not credentials.

The coordinator is thread-safe and keeps the active state in memory. When
configured with the deployment journal as its event sink, transitions are
persisted for operator review and restart reconciliation; live sessions and
active I/O are not resumed after a process restart. The coordinator itself
does not open sockets, start PXE/DHCP/TFTP, send multicast, mount repositories
or invoke storage utilities. It does not trigger disk writes.
