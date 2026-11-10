# ADR 0007: Cockpit as the primary operator interface

- Status: Accepted; Cockpit is the supported Live interface
- Date: 2026-11-08

## Context

Feclora requires a Clonezilla-like guided interface for image capture,
restoration and cloning, plus administration of its remote deployment
capabilities. The former `dialog` interface is not required; Cockpit Terminal
provides the low-level access needed for diagnostics and administration.

## Decision

Build Feclora as a dedicated Cockpit application using React and PatternFly.
Cockpit is the primary operator interface, not an optional read-only dashboard.
Do not fork Anaconda or depend on Anaconda Web UI internals.

The frontend calls a separately testable Python backend through a root-owned
wrapper and Cockpit's superuser authorization. The API accepts bounded JSON,
fixed allowlisted actions and exact typed confirmations. It exposes no shell
or arbitrary argv. Storage and deployment engines remain independent of
Cockpit and must revalidate every destructive operation.

Local whole-disk and partition capture/restore and local disk/partition clone
are exposed in the Operations wizard. The UI also provides inventory, image
inventory, security-key setup, deployment journal summaries and system
status. Cockpit Terminal is the supported general-purpose shell.

Server/Client configuration, certificate enrollment, persistent unicast
save/restore, multicast restore job setup, repository management and local
network configuration are now exposed in Cockpit. Remote clone and PXE-to-job
handoff still have incomplete acceptance coverage; live per-client multicast
progress and results remain outstanding. Track exact scope in the feature
matrix and implementation plan.

## Consequences

- Cockpit is the default operator interface; the `dialog` package and
  local-rescue dialog menu are removed from the Live package.
- Cockpit socket activation is enabled in the Live image. The operator sets
  a non-empty live-user password and explicitly permits the Cockpit service
  through firewalld on a trusted management network.
- The browser never constructs shell commands or invokes arbitrary tools.
- ISO generation, BIOS/UEFI boot, hardware restoration and network laboratory
  acceptance remain operator validation tasks.
