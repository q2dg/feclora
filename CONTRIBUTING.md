# Contributing to Feclora

This document describes the engineering and review expectations for
contributions to Feclora. The project is a Fedora Live rescue environment:
correctness and storage safety take priority over feature count.

## Before changing code

- Read the relevant operator documentation and the current
  [roadmap](docs/ROADMAP.md) and [implementation plan](docs/IMPLEMENTATION-PLAN.md).
- Check the relevant architecture and protocol documentation before changing persisted formats, trust boundaries or wire behavior.
- Keep Cockpit as the primary operator interface. Privileged operations belong
  behind the allowlisted Python API; browser code must not execute privileged
  commands or construct arbitrary shell commands.
- Preserve compatibility deliberately. If a persisted journal, manifest,
  configuration, or wire protocol changes, document its schema and migration
  behavior and add regression tests.

## Implementation requirements

- Keep destructive operations fail-closed. Validate source and destination
  independently, recheck device identity and mount/root safety immediately
  before I/O, and require an explicit operator confirmation.
- Never silently resume an interrupted destructive operation.
- Do not log private keys, credentials, decrypted secrets, or unrestricted
  device contents.
- Treat network identity, MAC addresses, filenames, and UI-supplied values as
  untrusted input. Authenticate peers cryptographically; a MAC address is an
  inventory identifier, not an authenticator.
- Keep TLS control-plane guarantees distinct from data-plane guarantees.
  In particular, document the security properties and limitations of UDPcast
  and other transports accurately.
- Prefer small, independently testable modules. Avoid unrelated refactors and
  preserve historical ADRs.
- Update the Cockpit UI, API validation, automated tests, operator docs,
  feature matrix, and roadmap together when a feature crosses those layers.

## Validation

Run the hardware-independent checks from the repository root:

```bash
make validate
make test
make webui
```

The Python tests use the standard-library unittest runner. The frontend build
uses the exact dependency versions listed in `webui/package.json`. Until a
committed npm lockfile is present and CI uses `npm ci`, dependency resolution
is not fully locked.

Changes to shell scripts must pass Bash syntax validation and ShellCheck.
Changes to the frontend must compile successfully. CI must pass on the exact
commit being proposed.

## Storage and deployment safety

- Unit tests must use temporary files, mock devices, or explicitly controlled
  test doubles. Never point automated tests at a host's real block devices.
- Do not run real destructive restore, clone, repartition, or deployment tests
  as part of ordinary development or CI.
- Hardware, BIOS/UEFI, PXE, switch IGMP, and destructive restore acceptance
  must be performed by an operator on disposable laboratory equipment and
  recorded separately from automated test results.
- ISO generation and physical restoration are operator-owned acceptance
  steps; the documented build procedure is not evidence that an ISO has been
  built or boot-tested.

## Documentation and scope

Document new operator-visible behavior, prerequisites, warnings, recovery
procedures, and limitations. Mark a roadmap item complete only when its
implementation, Cockpit integration where applicable, and automated
non-destructive validation are complete. Keep hardware acceptance explicitly
separate.

Feclora is licensed under the GNU General Public License v3.0 or (at your
option) any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
Individual components and dependencies may carry separate licenses; preserve
their applicable notices and terms when incorporating or redistributing them.
