# UDPcast multicast transport

Feclora uses UDPcast only as a **data-plane file transport**. Client identity,
job authorization, readiness, target selection and result reporting belong to
the authenticated control plane; a UDPcast rendezvous packet, multicast
membership, source IP or MAC address is never proof of identity.

## Implemented adapter boundary

`feclora.network.udpcast` provides:

- strict IPv4 multicast/interface/port/TTL/bitrate/FEC configuration validation;
- shell-free `udp-sender` and `udp-receiver` argv builders;
- a sender gate requiring the deployment coordinator to be explicitly armed,
  plus signed-manifest verification and source artifact size/SHA-256 checks;
- receiver staging into a private mode-0600 temporary file, with a free-space
  preflight and exact expected-size check;
- a separate post-reception verification step that verifies the detached
  minisign signature against an independently trusted public key, parses the
  manifest and checks the complete staged artifact SHA-256 and byte count.

The adapter does **not** write to block devices, select a restore target,
authenticate clients, establish TLS, or mark a deployment client successful.
Its firewalld scope is integrated with the existing temporary PXE zone when
both use the same firewall-manager instance.
The caller must complete the TLS 1.3 mutual-authenticated control handshake,
bind the peer certificate identity to an authorized job client, collect local
target authorization/readiness, and call the coordinator before the sender
function. On the receiver, the authenticated control service must deliver the
expected signed manifest metadata and target authorization independently of
UDPcast. Only after `verify_staged_multicast_artifact` succeeds may the
existing protected restore workflow be called. Keep the staged file until the
restore workflow has completed and recorded its per-client result.

## Network contract

- Data and rendezvous groups are distinct IPv4 multicast addresses.
- Portbase is even; UDPcast uses portbase and portbase+1. Both peers must use
  the same portbase.
- TTL defaults to 1; increase only after explicit multicast-routing review.
- The sender does not use UDPcast `--autostart`; its process starts only after
  the deployment coordinator is armed. `--nokbd` is used because Feclora owns
  the explicit start gate.
- The default bitrate is 100 Mbit/s, with a hard configuration ceiling of 10 Gbit/s; FEC is optional.
- A firewalld manager is mandatory. If the PXE zone is already active in the same
  manager, the adapter temporarily adds only these UDP ports and removes them
  afterwards, preserving DHCP/TFTP/HTTP rules. Otherwise it creates a temporary
  interface-exclusive zone with only the UDPcast ports and restores the prior
  interface assignment on exit.

UDPcast uses a two-port base and its multicast rendezvous/data-address options;
see the [udp-sender manual](https://manpages.debian.org/unstable/udpcast/udp-sender.1.en.html)
and [upstream command-line documentation](https://www.udpcast.linux.lu/cmd.html).

## Remaining integration and acceptance work

The authenticated control service, persistent job journal, Client-side whole-disk
restore runtime, signed-manifest delivery, private staging, and per-client
terminal results are integrated in the current application. The following
work remains:

1. Extend the authenticated deployment protocol and Client UI to support
   manifest-backed **partition-image** multicast restore to an already existing
   target partition. Keep whole-disk restore as the only multicast mode until
   this path has its own target-approval and geometry checks.
2. Add automated multicast interface/subnet capability preflight, including
   local route/interface checks and clear diagnostics for IGMP snooping and
   querier requirements. Retain an explicit operator fallback to one-to-one
   unicast; do not silently change transport mid-job.
3. Add per-client live byte progress and streaming logs without weakening the
   explicit start/cancel gates.
4. Execute the sender and multiple receivers in isolated BIOS/UEFI VMs and on
   networks with IGMP snooping/querier. Test packet loss, insufficient space,
   wrong signatures, wrong hashes, receiver loss, cancellation and recovery.

This document describes the adapter and remaining work; it is not evidence
that end-to-end multicast or VM acceptance has passed.
