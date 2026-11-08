# Feclora Cockpit application

Feclora's React/PatternFly application is its primary operator interface.

The Operations wizard exposes whole-disk and partition image capture,
restoration, disk-to-disk cloning and partition-to-partition cloning. It
supports device inventory, image selection, compression, local age encryption,
minisign signatures, exact destructive confirmations and streamed progress.
Other tabs provide storage inventory, image inventory, deployment journal
summaries, system status and an initial Server identity bootstrap wizard. The
bootstrap wizard validates an assigned IPv4 address, warns about a detected
DHCP server and initializes managed trust material; it does not start PXE or
deployment services. Cockpit Terminal provides system administration and
diagnostic shell access.

Build with `npm install` followed by `npm run build`. The ISO build copies
`dist/` into `/usr/share/cockpit/feclora`.

The frontend invokes only fixed actions through the root-owned
`/usr/libexec/feclora/cockpit-api` wrapper. Requests are bounded JSON on
stdin. Cockpit superuser authorization is required for privileged operations.
No arbitrary shell or argv is exposed by the Feclora API.

Remote Server/Client setup, enrollment, PXE job management, remote clone and
per-client multicast progress still need Cockpit workflows.
