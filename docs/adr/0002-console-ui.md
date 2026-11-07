# ADR 0002: Initial console interface

- Status: Accepted
- Date: 2026-11-07

## Context

feclora is initially a rescue Live environment. It must remain usable without
network access, a browser, or a running web service. The storage/imaging engine
must not depend on a particular user interface.

## Decision

Use the standard `dialog` utility for the first console interface. Keep the
UI in `feclora.ui` and keep storage operations in separate modules. The
initial screen is inspection-only: it lists block devices and displays
metadata. It must not offer destructive actions.

Cockpit is not part of the initial Live image. It may be evaluated later for a
separate server/remote-administration edition, where its service lifecycle,
authentication, network exposure, and resource cost can be assessed explicitly.

## Consequences

- The first UI works in a local text console and does not require a network.
- The UI adds only the standard `dialog` package.
- Future interfaces can call the same engine without reimplementing storage
  operations.
- Similarity to Clonezilla's navigation is useful, but feclora does not copy
  Clonezilla's implementation or inherit its upstream dependencies.
