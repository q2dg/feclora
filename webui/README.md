# Feclora Cockpit application

Feclora's React/PatternFly application is its primary operator interface.

The Operations wizard exposes whole-disk and partition image capture,
restoration, disk-to-disk cloning and partition-to-partition cloning. It
supports device inventory, image selection, compression, local age encryption,
minisign signatures, exact destructive confirmations and streamed progress.
Other tabs provide storage inventory, image inventory, durable local operation
history, Server identity and trusted-Client administration, removable-media
Client enrollment and renewal, Server deployment-job authoring/lifecycle,
Client job inspection and execution, PXE preflight and service activation, and
system status. Server/Client storage jobs use READY/ARM authorization gates;
PXE service activation is a separate, explicit operation. Cockpit Terminal
provides system administration and diagnostic shell access.

Build with `npm install` followed by `npm run build`. The ISO build copies
`dist/` into `/usr/share/cockpit/feclora`.

The frontend invokes only fixed actions through the root-owned
`/usr/libexec/feclora/cockpit-api` wrapper. Requests are bounded JSON on
stdin. Cockpit superuser authorization is required for privileged operations.
No arbitrary shell or argv is exposed by the Feclora API.

Remote disk-to-disk cloning is not yet integrated into the persistent services
or Cockpit. The remote clone protocol/runtime is a separate foundation and
must not be confused with the existing Server/Client image-deployment jobs.
Server-side transfer-byte telemetry also remains incomplete; Client-local
progress and deployment job states are available.
