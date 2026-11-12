# Feclora Cockpit application

Feclora's React/PatternFly application is its primary operator interface.

The Operations wizard exposes whole-disk and partition image capture,
restoration, disk-to-disk cloning and partition-to-partition cloning. It
supports device inventory, image selection, compression, optional `age` encryption
and optional `minisign` signatures, exact destructive confirmations and streamed progress.
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

Remote whole-disk cloning is available as a distinct unicast job in the
existing persistent Server/Client lifecycle. The Server selects a read-only
source disk and selects the Client MAC for this job; the Client selects
and confirms its local destination. The Client verifies the Server certificate; neither endpoint uses Client
certificates. Both use the existing Server-authenticated TLS control session, durable job journal and managed services. Clone streams directly
between block devices through the existing bounded remote-clone engine; it
does not use UDPcast or create a second service stack. Server-side byte
progress is exposed through the existing per-Client job status.
