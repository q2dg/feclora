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

## Live ISO integration status

The build script now stages `src/feclora` under `out/feclora-app`, adds that
directory to a temporary copy of the Fedora installer DVD with `mkksiso`, and
passes the augmented DVD to `livemedia-creator`. A Kickstart `%post --nochroot`
section copies the payload into `/usr/share/feclora/python/feclora` and creates
`/usr/local/bin/feclora-ui`.

This removes the need for a network download or a separately hosted package
repository. The payload is copied from the installer media into the installed
live filesystem using Anaconda's documented `--nochroot` post-install mode.
The pipeline change is implemented, but the ISO has not yet been built or boot
tested; keep the roadmap item open until those checks pass.

## Why not Cockpit yet?

Cockpit is a credible option for a future server-oriented edition. For the
initial offline rescue image, a local TUI avoids a web server, browser,
network-facing management endpoint, and additional service configuration.
Revisit Cockpit when remote administration becomes a concrete requirement.
