# Direct physical-disk multicast

## Status

Not integrated. The existing UDPcast multicast restore still transports manifest-backed image artifacts into private Client staging directories; it does not stream a Server block device directly into Client block devices. A new isolated safety module now provides fail-closed source/destination identity and geometry checks, identity revalidation, and exact-length stream write/read-back SHA-256 primitives with short-write handling. These primitives are not yet connected to UDPcast, the deployment job schema, Server/Client services, Cockpit, or durable per-client results. Do not describe physical multicast as implemented.

## Intended operation

1. The Server operator selects one whole physical disk. The server reopens it read-only and records a stable identity tuple (major/minor, sysfs path, WWN, serial, size and logical/physical sector sizes). The identity and geometry are rechecked immediately before streaming.
2. The operator selects the Client set and multicast network parameters. The job definition records the source identity and geometry, but never trusts a browser-supplied device path as proof of identity.
3. Each Client independently inventories its local disks, selects one destination and explicitly approves it. The Client sends its observed identity and geometry over the authenticated control channel.
4. The Server rejects the job unless every selected Client is READY and every destination is independently validated. A destination is rejected if it aliases the source device (including major/minor identity), is mounted, backs the running system, is otherwise busy, is smaller than the source, or has incompatible sector geometry.
5. Only after the operator enters the job-specific arm phrase does the Server stream raw bytes from the read-only source block device through UDPcast. The Server must not create a RAW/IMG staging artifact.
6. Each Client writes the received stream directly to its approved block device. It tracks the exact byte count, handles short writes, flushes and fsyncs, then reads back the written range and compares SHA-256 against a digest calculated by the Server for the exact source stream. The control channel records per-client results.
7. A Client is successful only after readback verification. Post-actions (none/reboot/poweroff) are permitted only for individually verified clients and must use the existing strict allowlist.

## Safety invariants

- Never open the Server source writable. Never write to the Server source.
- Never infer identity from device names alone. Revalidate stable identity and major/minor immediately before use.
- Never permit source/destination aliasing, including multipath or alternate device-node aliases.
- Never let a Client accept a destination chosen by the Server. Client-local approval is mandatory.
- No writes before all required READY responses and explicit Server authorization.
- No automatic retry after a partial physical write. Mark the Client as requiring operator inspection; do not resume from an uncertain offset.
- No destructive integration tests against host block devices. Use regular-file-backed fake block-device abstractions and injected readers/writers.
- Do not weaken existing TLS control authentication, job journaling, threshold/deadline policy, or post-action allowlists.

## Protocol and implementation boundaries

Use the existing authenticated deployment control channel for job metadata, readiness, authorization and per-client results. UDPcast is only the data plane. Add a new operation identifier rather than overloading clone or restore; its schema must bind the source identity, source geometry, destination approval, stream length and digest algorithm.

The Server must calculate a streaming digest while reading the source. Every receiver must independently calculate a digest while writing and perform a readback digest after flush. If the source cannot be read consistently, the stream length changes, any receiver disconnects, or any digest differs, the job fails closed.

Do not route this operation through image manifests, repository managers, S3, or temporary image artifacts: the defining property is direct physical block-device streaming.

## Required automated coverage

- source is opened read-only and source identity changes are rejected (identity validation primitives added; actual source opening/revalidation integration remains outstanding);
- destination alias detection across device nodes and major/minor identities (major/minor and sysfs alias checks covered by the new safety primitive);
- mounted, system-backed, undersized and incompatible-sector destinations rejected (preflight primitive implemented; runtime inventory binding remains outstanding);
- no data-plane start before all READY and explicit arm;
- source read errors and short reads fail closed;
- receiver short writes are handled and flush/read-back verification is required by the new stream primitive; flush errors, disconnects and durable incomplete-state reporting still need runtime integration;
- successful stream requires byte-count and readback digest agreement per Client (in-memory stream primitive added; not yet connected to UDPcast);
- one failed Client does not cause successful post-actions on that Client;
- no retry/resume after uncertain partial writes;
- fake I/O only; no physical block devices in CI.

## Acceptance boundary

Implementation is not complete until the Cockpit workflow, durable job schema/journal, Server runtime, Client runtime, UDPcast data plane, per-client readback verification, recovery state and automated tests are integrated. A design document or a passing mock transport test alone is not completion.
