# Deployment coordinator

`feclora.deployment.coordinator.DeploymentCoordinator` is the in-process
state machine shared by Server mode and the future network control service.

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
authentication mechanism. It must only be supplied by a future transport
adapter after verifying a cryptographic peer identity and job authorization.
MAC addresses are not credentials.

The coordinator is thread-safe and in-memory. It does not persist jobs, open
sockets, start PXE/DHCP/TFTP, send multicast, mount repositories, or invoke
storage utilities. Process restart loses its state. No disk writes can be
triggered through this module.
