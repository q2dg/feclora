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
  plus optional manifest-signature verification and source artifact size/SHA-256 checks;
- receiver staging into a private mode-0600 temporary file, with a free-space
  preflight and exact expected-size check;
- a separate post-reception verification step that verifies a detached signature when present and a trusted key is configured,
  parses the manifest and checks the complete staged artifact SHA-256 and byte
  count.

The adapter does **not** write to block devices, select a restore target,
authenticate clients, establish TLS, or mark a deployment client successful.
Its firewalld scope is integrated with the existing temporary PXE zone when
both use the same firewall-manager instance.
The caller must complete the TLS 1.3 mutual-authenticated control handshake,
bind the peer certificate identity to an authorized job client, collect local
target authorization/readiness, and call the coordinator before the sender
function. On the receiver, the authenticated control service must deliver the
expected manifest metadata and target authorization over the authenticated
TLS channel independently of UDPcast. A present signature must verify before
restore. Only after `verify_staged_multicast_artifact` succeeds may the
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

## Integrated behavior and remaining acceptance work

The authenticated control service, persistent job journal, Client-side
whole-disk and partition restore dispatch, signed-manifest delivery, private
staging, verified artifacts and per-client terminal results are
integrated. Unsigned manifests are accepted when delivered through the
authenticated mTLS control channel; detached minisign signatures are verified
when present and require an independently trusted key.

- The deployment job binds `target_type` to the signed manifest's
  `image_type`. A disk job cannot be paired with a partition manifest or vice
  versa.
- Partition restore targets an already existing local partition. The Client
  selects it locally, verifies capacity and safety constraints, and requires
  explicit typed authorization. Feclora does not create, resize or repartition
  targets.
- `age` encryption is optional and must not be required for ordinary Feclora
  operation. When enabled, artifacts are encrypted for the configured recipient
  inventory. When disabled, UDPcast provides no payload confidentiality; use a
  trusted isolated network or another configured encryption layer.
- Manifest authenticity is required before destructive restore, but `minisign`
  is only the current implementation. The verifier must become configurable so
  another trusted signature mechanism can be used without making minisign mandatory.
  This does not add per-datagram authentication to UDPcast and cannot prevent
  denial of service.
- Sender and receiver check local interface UP/MULTICAST flags, IPv4 address,
  kernel route to the multicast group and required UDPcast executable. Switch
  IGMP snooping and querier state cannot be proven from an endpoint and remains
  an operator check.
- Per-client live byte progress and streamed UDPcast metrics remain pending.
  Terminal per-client results, cancellation and cleanup are implemented.
- Sender/receiver behavior still needs automated integration execution and
  real BIOS/UEFI multi-VM acceptance. This document is not evidence that those
  tests passed.


## Optional crypto policy

UDPcast is a transport and does not encrypt/authenticate its data plane. Feclora
must not require `age` or `minisign` as global installation dependencies.
`age` may be enabled for confidentiality. A trusted manifest-authentication
mechanism remains mandatory before destructive restore; the current code uses
minisign and must gain a replaceable verifier interface to meet the project's
optional-minisign policy. SHA-256 alone is not an authenticity mechanism.