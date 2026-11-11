# Deployment job contract (schema version 1)

Server and Client modes share a validated JSON deployment-job document. The
job is a declarative description sent over the TLS 1.3 mutual-authenticated
control session. It is not a credential, Client identity, target-device path
or authorization to write. The Server still verifies the certificate identity
against its enrollment allowlist; each Client performs local device checks;
and the Server operator explicitly ARMs the complete READY set.

## Example: multi-Client restore with stable target bindings

~~~json
{
  "schema_version": 1,
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "operation": "restore",
  "image_id": "golden-image-2026",
  "target_type": "disk",
  "authorized_clients": ["52:54:00:12:34:56", "52:54:00:12:34:57"],
  "target_bindings": {
    "52:54:00:12:34:56": {
      "wwn": "0x5000cca123456789",
      "serial": "TARGET-001"
    },
    "52:54:00:12:34:57": {
      "wwn": null,
      "serial": "TARGET-002"
    }
  },
  "network_interface": "enp1s0",
  "transport": "multicast",
  "multicast_group": "239.10.10.10",
  "multicast_port": 5000,
  "start_policy": "manual",
  "expected_clients": null,
  "start_deadline": null
}
~~~

## Field rules

- `schema_version`: exactly `1`.
- `job_id`: canonical UUID identifying one deployment attempt.
- `operation`: `save`, `restore` or `clone`. Clone is the direct
  whole-disk Server-to-Client stream and requires unicast/manual start.
- `image_id`: simple repository identifier for save/restore; clone jobs must
  set it to null.
- `target_type`: `disk`, `partition` or `logical_volume`. Logical-volume
  targets are valid only for restore jobs. Save and clone currently support
  whole disks only. A Client (interactive or persistent Cockpit mode) selects its own existing LV
  locally; the job never carries a Client device path.
  Raw LUKS2 container images use the same `partition` target type: unicast
  and multicast Clients dispatch them to the partition restore engine, which
  validates encrypted-container provenance and the included header UUID,
  writes raw ciphertext/header/keyslot bytes, verifies read-back and the
  resulting LUKS2 JSON metadata, and leaves the mapping closed. The Client
  must have `cryptsetup`; age-encrypted artifacts additionally need its local
  age identity. No passphrase or keyslot material is sent as a deployment
  control field. Opened-mapping plaintext images and LUKS2-on-LV remain
  unsupported. The persistent service
  and Cockpit API independently validate the selected LV against healthy local
  LVM topology before reporting READY.
- `authorized_clients`: non-empty allowlist of unique unicast MAC addresses.
  MAC is an inventory mapping key, not cryptographic authentication.
- `target_bindings`: optional object for whole-disk restore jobs, keyed by an
  authorized Client MAC. If present, it must bind every authorized Client.
  Each value contains exactly `wwn` and `serial`; at least one must be supplied.
  The Client compares every supplied identifier with its own current device
  inventory before READY. A mismatch or missing identifier rejects the
  selected device. These hardware fields reduce accidental mis-targeting;
  they are not cryptographic device attestation and may be spoofable. The Server Cockpit whole-disk restore workflow can collect a binding
  for each selected Client; partition- and logical-volume target bindings are not currently
  supported because those targets require local topology-aware selection. This is a preflight constraint: it does not yet
  provide unattended target discovery or replace the Client's local target
  selection and typed confirmation.
- `network_interface`: explicit Linux interface name; no implicit default.
- `transport`: `unicast` or `multicast`. Multicast requires an
  administratively scoped IPv4 group and an even UDPcast port base.
- `multicast_group` and `multicast_port`: required only for multicast.
- `start_policy`: `manual`, `expected_clients` or `deadline`; the latter
  two require exactly one matching threshold/deadline parameter.
- `staging_required_bytes`: optional non-negative capacity requirement used
  only for multicast restore jobs.
- `source_device`: normalized Server-local /dev path, required only for
  direct clone jobs. It identifies the source, never a Client destination.
- `repository_id`: optional managed repository identifier for restore jobs;
  it is not a filesystem path.

Unknown fields and unsupported schema versions are rejected. Older schema-v1
jobs without optional fields remain readable.

## Safety boundary

The schema never contains a Client destination /dev path, shell command,
arbitrary executable, password or private key. A stable WWN/serial binding is
not a path and cannot be used to bypass local inventory or safety checks.
Without a binding, the established interactive Client target-selection path
remains in effect.

A logical-volume restore is preflighted against the Client local LVM inventory
and must target an existing active, unmounted linear or thin LV. The restore
engine re-collects inventory immediately before writing. It never creates,
resizes, activates or otherwise changes PV/VG/LV metadata. RAID, striped,
cache, snapshot and unknown layouts are rejected.

A parsed job does not authenticate a peer or start a write. Production control
traffic uses TLS 1.3 mutual authentication. The Server maps the authenticated
certificate identity to an enrolled Client and then checks job membership.
The Client checks its own selected target and reports READY only after local
preflight and typed confirmation. The Server requires the complete authorized
READY set and a separate explicit ARM action before it sends START.

PXE boot parameters and the job UUID are public handoff metadata only.
The current unattended PXE path obtains mTLS credentials from a dedicated
per-Client removable medium, authenticates the enrolled certificate, requires
a WWN/serial binding for unicast whole-disk restore, and retains this job
schema's READY/ARM authorization. Partition/multicast unattended execution
and interrupted-job expiry/replay acceptance remain outside the current path.

## Managed remote image repository

A restore job may include the optional `repository_id` field. It is a simple
managed-repository identifier, never a filesystem path. Job creation resolves
it through the root-owned repository registry and requires the corresponding
mount to be active and verified before reading the image manifest. Persistent
Server startup resolves the same ID again and verifies the image trust policy
before accepting the job. The selected mount must remain available for the
lifetime of the restore.

Cockpit's remote restore workflow exposes mounted, verified repositories.
Unicast and UDPcast multicast restore use the same selected repository. Save
and direct clone jobs do not accept `repository_id`; Client captures continue
to use the Server's configured repository.
