# ADR 0004: feclora Server Edition architecture

- Status: Accepted as target architecture
- Date: 2026-11-07
- Scope: centralized network imaging and deployment

## Decision

feclora will target both Clonezilla Live-style standalone rescue and Clonezilla Server Edition-style centralized deployment. Server mode is a separate role/edition built around generic Linux tools and standard network protocols; it is not a dependency on Clonezilla or DRBL.

The server role will contain:

1. A control plane for deployment jobs, client eligibility, scheduling, concurrency and results.
2. Standard network boot services/integration: DHCP configuration or safe integration with existing DHCP, TFTP, PXE/iPXE and HTTP boot where supported.
3. A repository/data plane supporting local storage and standard network repositories/transports.
4. A client runtime that boots into a feclora environment and executes authorized jobs using the same generic storage tools as Live mode.
5. Unicast and multicast/broadcast data delivery. UDPcast is the initial candidate for multicast; it must be evaluated and tested before commitment to a production package/interface.

## Safety requirements

- Never start a deployment for arbitrary PXE clients by default.
- Require explicit job arming and a client allowlist/identity policy.
- Make the deployment interface and DHCP/PXE network scope explicit.
- Never silently start a competing DHCP server or modify an existing network.
- Keep client target selection and root/system-device safeguards active.
- Require isolated disposable clients for integration tests.
- Report per-client state and failure; do not declare success on sender exit alone.

## Non-goals

No DRBL, no Clonezilla ocs-* commands/scripts, and no private Clonezilla orchestration. Generic storage utilities and standard protocols are the implementation substrate.

## Consequences

Server mode is a substantial milestone beyond the current single-machine read-only TUI. It will be implemented after local save/restore/clone primitives and the image/job contracts have been tested. The existing Fedora Live ISO remains the initial rescue target; server edition packaging and installation will be designed separately so that network services are not enabled unintentionally in a portable rescue ISO.