# Deployment job contract (schema version 1)

Server and Client modes in the single feclora ISO share a validated JSON job
document. The current implementation is a local parser/validator only; it does
not open sockets, start services, authenticate peers, mount images or write
storage.

## Example

```json
{
  "schema_version": 1,
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "operation": "restore",
  "image_id": "golden-image-2026",
  "authorized_clients": ["52:54:00:12:34:56"],
  "network_interface": "enp1s0",
  "transport": "multicast",
  "multicast_group": "239.10.10.10",
  "multicast_port": 5000,
  "start_policy": "expected_clients",
  "expected_clients": 1,
  "start_deadline": null
}
```

## Field rules

- `schema_version`: currently exactly `1`.
- `job_id`: UUID identifying one deployment attempt.
- `operation`: `save` or `restore`; disk-to-disk clone is a local workflow and
  is not represented as a network deployment operation yet.
- `image_id`: simple repository identifier, never a filesystem path or shell
  fragment. The server resolves it against its configured repository.
- `authorized_clients`: non-empty allowlist of unique MAC addresses. This is
  an identity filter, not cryptographic authentication.
- `network_interface`: explicit Linux interface name; no implicit default.
- `transport`: `unicast` or `multicast`. Multicast requires an IPv4 multicast
  group and UDP port 1024–65535.
- `start_policy`: `manual`, `expected_clients`, or `deadline`. The latter
  two require exactly one matching threshold/deadline parameter.

## Safety boundary

The schema deliberately does not contain a client block-device path, shell
command, arbitrary executable, or arbitrary output path. A client must perform
its own device inventory and safety checks. Destructive target selection and
confirmation are not delegated to a remote image/job document.

MAC allowlisting alone is not authentication: production control traffic must
use an authenticated, integrity-protected protocol and per-job authorization
before any client accepts a job. The schema parser does not claim to provide
that security layer.

Unknown fields and unsupported schema versions are rejected. No job can cause
a disk write merely by being parsed.


## Restore from a managed remote image repository

A restore job may include the optional `repository_id` field. It is a simple
managed-repository identifier, never a filesystem path. Job creation resolves
it through the root-owned repository registry and requires the corresponding
mount to be active and verified before reading the signed image manifest.
Persistent Server startup resolves the same ID again and verifies the image
signature before accepting the job. The selected mount must remain available
for the lifetime of the restore.

Cockpit's remote restore workflow exposes only mounted, verified repositories
and signed images. Multi-Client unicast and UDPcast multicast restore use the
same selected repository. Save and direct clone jobs do not accept
`repository_id`; Client captures continue to use the Server's configured
repository.
