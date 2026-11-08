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
- The default bitrate is capped at 100 Mbit/s and FEC is optional.
- A firewalld manager is mandatory. If the PXE zone is already active in the same
  manager, the adapter temporarily adds only these UDP ports and removes them
  afterwards, preserving DHCP/TFTP/HTTP rules. Otherwise it creates a temporary
  interface-exclusive zone with only the UDPcast ports and restores the prior
  interface assignment on exit.

UDPcast uses a two-port base and its multicast rendezvous/data-address options;
see the [udp-sender manual](https://manpages.debian.org/unstable/udpcast/udp-sender.1.en.html)
and [upstream command-line documentation](https://www.udpcast.linux.lu/cmd.html).

## Remaining integration and acceptance work

1. Add the mTLS control service and a persistent job/session store around the
   existing coordinator; MAC allowlists remain an additional policy, not auth.
2. Implement the Client mode runtime: certificate identity, independent local
   target selection, capacity/geometry checks, staging-volume selection,
   signed-manifest delivery, receive, verify, protected restore, and result ACK.
3. Add UDPcast ports to a scoped temporary firewalld zone with rollback and
   restoration of the original interface zone.
4. Integrate per-client progress/results and cancellation; ensure partial
   staging files are cleaned up after failure or cancellation.
5. Exercise sender plus multiple receivers in isolated BIOS/UEFI VMs and on
   networks with IGMP snooping/querier; test packet loss, insufficient space,
   wrong signatures, wrong hashes, receiver loss and cancellation.

No end-to-end multicast deployment or VM validation is claimed by this adapter.
