# Direct physical-disk multicast

## Status

The low-level physical multicast clone protocol, Client receiver path, and Server worker branch are implemented, but the persistent end-to-end path is currently blocked by two stale validation gates: `DeploymentService` accepts multicast restore jobs only, and the Client `start_client_job` API also rejects multicast clone jobs. The GTK interface can display the workflow, but they must not be described as operational or accepted until both gates are reconciled and the complete service path is tested. The intended contract remains the existing `clone` operation with `multicast` transport; it is separate from multicast image restore. The implementation binds the Server source identity at job creation, validates the selected Client cohort, reads the source through a read-only block descriptor, and has Clients independently select and approve whole-disk destinations before exclusive open and physical-ready acknowledgement.

The data stream travels directly from the Server block device through UDPcast to Client block descriptors. No RAW/IMG staging file or image repository is involved. Every Client flushes and reads back the exact written range and compares SHA-256. Per-client terminal results use the existing durable deployment journal; configured post-actions remain restricted to Clients that report successful verification.

Automated coverage uses fake/in-memory I/O only. Real multi-host UDPcast/IGMP acceptance and disposable-media operator validation remain outstanding. Do not test against valuable or host system disks.

## Operation and safety gates

1. The Server operator selects a whole physical disk that is already marked read-only. At job creation, the privileged API captures its major/minor, sysfs path, WWN/serial, capacity and sector geometry as the immutable source binding.
2. The job must use multicast transport, at least two selected Clients, and the manual start policy. The operator configures the Server multicast interface, group and even UDPcast port base.
3. Each Client independently selects and types confirmation for a local whole-disk destination. Before READY, the Client inventories its identity, geometry, mountpoints, holders and system-use state.
4. The Server requires every explicitly selected Client to be READY, not merely a threshold. It revalidates each host's local path, major/minor and sysfs identity, and rejects cross-host hardware aliases by WWN/serial, including a destination shared by two Clients. It also rejects mounted, held, system-backed or busy devices, undersized targets, and logical/physical sector mismatches.
5. The Server opens the bound source read-only and computes the expected SHA-256. It sends the exact byte count and digest with START. Each Client then re-inventories its destination, compares it with its READY identity, opens it read/write with Linux `O_EXCL`, starts `udp-receiver`, and sends a separate physical-ready acknowledgement.
6. The Server waits for every selected Client's physical-ready acknowledgement before starting `udp-sender`. It streams exactly the source disk capacity from the read-only descriptor. No intermediate image artifact is created.
7. Each Client writes directly to its approved block descriptor with positional I/O, handles short writes, fsyncs, reads back the exact range and compares SHA-256 with the Server digest. It sends a terminal result only after verification.
8. A Client may request the configured fixed post-action only after its own successful read-back and successful result report. Failed or interrupted Clients are not rebooted or powered off.

## Trust and network boundaries

- TLS authenticates the Server to Clients and protects the control channel. Each Client reports its MAC address for job selection and status association; this is not cryptographic proof of machine identity.
- UDPcast multicast payloads are not encrypted or authenticated. Use only on a trusted, isolated deployment network with suitable IGMP snooping/querier configuration.
- The Server source is never opened writable. Client destinations are never selected by the Server.
- Each host's path, major/minor and sysfs identity are revalidated locally; the opened descriptor's block major/minor is checked to close path-reuse races. Cross-host alias detection uses comparable WWN/serial values because `/dev` paths, dev_t values and sysfs paths are host-local. Client destinations must also be mutually distinct.
- Any incomplete or failed physical write requires operator inspection. The operation does not automatically retry or resume.
- Tests use fake descriptors, temporary sysfs fixtures and in-memory streams only. No physical block-device writes are performed by CI.

## Remaining acceptance

The implementation components have fake-I/O and protocol coverage, but the persistent service/API gates currently prevent this path from running end to end. First reconcile the Server `DeploymentService` multicast-operation guard and Client `start_client_job` multicast-operation guard with the existing physical-clone worker/receiver paths. Then add persistent-service/API tests proving the full READY/physical-ready/UDPcast sequence is reachable. Only after those software gates pass should operational acceptance proceed on disposable disks and multiple isolated VMs: verify multicast routing, IGMP behavior, UDPcast version/CLI compatibility, receiver-loss handling, read-back throughput and power actions. Do not mark hardware/network acceptance complete until those tests have actually been performed.
