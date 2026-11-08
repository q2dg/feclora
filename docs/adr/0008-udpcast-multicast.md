# ADR 0008: Multicast image distribution with UDPcast

- Status: Accepted for initial multicast transport; integration and security validation pending
- Date: 2026-11-08

## Context

Feclora Server must be able to distribute one disk image to multiple PXE-booted
clients without sending a separate full copy over unicast to every machine.
The existing deployment coordinator is responsible for explicit job arming,
client readiness and job state; the data plane must not bypass those controls.

## Decision

Use Fedora's UDPcast implementation (udp-sender and udp-receiver) as the
initial multicast data-plane transport. It is designed to distribute a file or
disk image to multiple LAN receivers over IP multicast, with one shared
datastream. Its options include receiver thresholds/time windows, rate limits,
retransmission/FEC controls and explicit interface/port selection.

Use the existing Feclora authenticated control plane separately to:
- authenticate each client with mutual TLS and validate its certificate identity;
- authorize the explicitly armed job and the client's locally selected target;
- agree on the image manifest, expected byte count, digest, multicast group,
  interface, ports and transfer parameters;
- collect readiness and final per-client results.

UDPcast is a transport, not the Feclora authentication or authorization layer.
Do not treat a MAC address, PXE boot request, multicast group membership or
UDPcast receiver discovery as authentication. Do not expose UDPcast sessions
to an untrusted network.

The first implementation must use a staging artifact on each receiver:
receive to a temporary file, validate the signed manifest and complete
payload digest, then invoke the existing protected restore path. It must not
stream unauthenticated multicast bytes directly onto a destination disk.
If staging capacity is insufficient, fail before arming/starting the transfer;
a future authenticated per-chunk transport may be considered separately.

Use a configurable multicast group and TTL=1 by default for a single LAN.
Require explicit operator selection of the network interface and ports. The
network must support multicast forwarding; switch IGMP snooping/querier and
router multicast configuration must be checked for the actual topology.
Provide unicast fallback for one-to-one deployments or networks where
multicast is unavailable.

## Consequences

- A single sender stream can serve many receivers, reducing duplicate traffic
  compared with N independent unicast transfers.
- Multicast reliability, packet loss, FEC/retransmission settings and bitrate
  need measurement on representative switches and NICs.
- UDPcast does not provide Feclora's mTLS identity, job authorization or
  end-to-end cryptographic payload authentication; these remain separate
  responsibilities.
- UDPcast package inclusion does not mean multicast runtime is implemented.
  Sender/receiver lifecycle, firewall rules, staging, digest/signature checks,
  cancellation, per-client results and VM tests remain required.

## References

- UDPcast project: https://www.udpcast.linux.lu/
- UDPcast command-line options: https://www.udpcast.linux.lu/cmd.html
- udp-sender manual: https://manpages.debian.org/udpcast/udp-sender.1.en.html
- Fedora UDPcast package: https://packages.fedoraproject.org/pkgs/udpcast/udpcast/
