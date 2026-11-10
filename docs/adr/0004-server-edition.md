# ADR 0004: Single-ISO multi-mode architecture

- Status: Accepted for single-ISO role architecture; startup dialog selector superseded by ADR 0007
- Date: 2026-11-07
- Scope: local rescue, server deployment and network client modes

## Decision

feclora will ship one Fedora-based bootable ISO. At startup, an interactive
menu lets the operator select:

1. Local rescue (Live): local disk and partition imaging.
2. Server: centralized orchestration and network deployment services.
3. Client: join an authorized network imaging session.

This follows the single-image, role-selection model requested for feclora.
There will not be a separate Server ISO or separately maintained server
runtime image. All modes share the kernel, initramfs, storage tools, image
metadata, safety checks and base application.

## Mode activation

- The startup selector is the sole entry point for choosing a mode.
- Local rescue starts without enabling server-side network services.
- Server services (DHCP integration, TFTP/PXE/iPXE, control plane, repository
  and unicast/multicast data plane) are activated only after selecting Server
  and explicitly configuring the deployment interface and network scope.
- Client mode starts the client runtime and joins only an authenticated,
  explicitly authorized job.
- No deployment is triggered simply by booting or connecting a client.
- Returning from a mode or shutting down must stop role-specific services.

The menu may expose modes before their implementation is complete, but must
clearly report unavailable functionality and must not pretend to start it.
This is the current behavior for Server and Client mode.

## Generic implementation substrate

Storage operations use generic Linux tools (Partclone filesystem-specific
executables, dd, sfdisk, sgdisk, parted, compression and checksum utilities).
Network boot uses dnsmasq for DHCP/ProxyDHCP, PXE and read-only TFTP,
Fedora's iPXE BIOS/UEFI boot images for chainloading, and nginx for HTTP boot
assets. See [ADR 0006](0006-embedded-pxe-stack.md). UDPcast is a candidate
for multicast and must be evaluated before it is adopted.

## Safety requirements

- Never start a competing DHCP service silently or modify an existing network.
- Require explicit server job arming and client allowlisting.
- Bind network services to an explicitly selected interface.
- Keep client target selection and live-root/system-device safeguards active.
- Require isolated disposable clients for integration tests.
- Report per-client state and failure; sender exit alone is not deployment
  success.

## Non-goals

No DRBL, no Clonezilla ocs-* commands/scripts, and no private Clonezilla
orchestration. No separate Server ISO.

## Consequences

**Supersession note (2026-11-10):** the original dialog startup selector and
Local rescue menu were not retained in the supported Live image. [ADR 0007](0007-cockpit-web-interface.md)
supersedes that operator-interface decision: Cockpit is the supported primary
interface for local imaging and Server/Client administration. The single-ISO,
shared-runtime and explicit-role-activation principles in this ADR remain in
effect. Remote deployment and PXE feature completeness is tracked in the
current feature matrix and implementation plan.
