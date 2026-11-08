# User interface

## Cockpit is the primary interface

Feclora uses Cockpit with a React/PatternFly application as its primary
operator interface. The browser workflow is the supported path for local
storage inventory, whole-disk/partition image capture, restoration and
disk/partition cloning. Cockpit's Terminal page provides access to the
underlying Linux system for diagnostics and advanced administration.

There is no requirement to retain the old `dialog` console application.
Storage and deployment engines remain independent Python modules and are
called by the Cockpit backend; the browser does not assemble shell commands.

## Safety and operation lifecycle

The Cockpit API is an allowlisted privileged helper. It accepts bounded JSON
requests, validates exact parameter sets and typed destructive confirmations,
and delegates to the existing storage engines. Those engines re-check device
identity, source safety, destination geometry and image integrity immediately
before writing. Progress is streamed to the browser as newline-delimited
events.

The Cockpit frontend does not expose arbitrary command execution. Terminal
access is provided by Cockpit itself and is intended for system administration,
not as a bypass around Feclora's guarded storage operations.

## Build integration

The build script stages `src/feclora` and the built `webui/dist` on a
temporary copy of the Fedora installer DVD. The Kickstart installs the Python
package and Cockpit application into the Live filesystem. The ISO is not
built or boot-tested as part of source-only repository work.
