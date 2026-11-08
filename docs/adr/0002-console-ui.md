# ADR 0002: Initial console interface

- Status: Superseded by ADR 0007
- Date: 2026-11-07

## Context

Feclora initially used `dialog` as a local rescue prototype. The project
subsequently adopted Cockpit as the primary operator interface, with access
to Cockpit Terminal for low-level system administration.

## Historical decision

The first prototype used `dialog` to keep storage discovery and the initial
local rescue flow separate from the Python storage engines. That decision
was appropriate for the early read-only console browser but no longer defines
the product interface.

## Current decision

Cockpit is the primary operator UI. The old `dialog` application is not
included in the Live package. Local imaging operations are exposed through a
narrow privileged API and the shared Python storage engines. Terminal access
is available for diagnostics and advanced administration, not as a bypass
around Feclora's safety checks.

See ADR 0007 and `docs/COCKPIT.md`.
