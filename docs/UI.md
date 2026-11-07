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

The Kickstart currently installs the runtime dependencies (`python3` and
`dialog`), but it does not yet install the feclora Python package or its launcher.
The UI is therefore runnable from a source checkout, not from the generated
Live ISO. Do not treat the UI as integrated into the ISO until the package
installation path is implemented and a boot test confirms it works there.

The image build uses `livemedia-creator` with an Anaconda Kickstart. A future
packaging change must make the feclora package available to that installation
in a reproducible way; merely adding files to the build host or relying on a
GitHub download during `%post` is not sufficient.

## Why not Cockpit yet?

Cockpit is a credible option for a future server-oriented edition. For the
initial offline rescue image, a local TUI avoids a web server, browser,
network-facing management endpoint, and additional service configuration.
Revisit Cockpit when remote administration becomes a concrete requirement.
