# User interface

## Initial console browser

The initial UI uses the standard `dialog` utility. From a checkout:

```bash
./scripts/feclora-ui.sh
```

It displays devices reported by `lsblk` and allows their metadata and child
partitions to be inspected. The current prototype is deliberately read-only:
there are no clone, restore, format, partition-edit, mount, or unmount actions.

The interface is separate from the storage inventory and future imaging
backends. This is intentional: the same engine should be reusable by another
frontend without duplicating disk-handling logic.

## Why not Cockpit yet?

Cockpit is a credible option for a future server-oriented edition. For the
initial offline rescue image, a local TUI avoids a web server, browser,
network-facing management endpoint, and additional service configuration.
Revisit Cockpit when remote administration becomes a concrete requirement.
