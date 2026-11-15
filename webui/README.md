# Feclora Cockpit application

Feclora's React/PatternFly application is its primary operator interface.

Other tabs provide durable local operation history, SSHFS/NFS/SMB repository
management and image-engine integration, Server CA and TLS trust configuration, optional age recipient
management, Server deployment-job authoring/lifecycle, Client job inspection
and execution, DHCP/static IPv4 profile configuration, PXE preflight and
service activation, and system status. Server/Client storage jobs use
READY/ARM authorization gates. PXE service activation and unattended answer
publication are explicit operations. Cockpit Terminal provides system
administration and diagnostic shell access.

Build the frontend from the repository root with
`bash build/build-webui.sh`. The script requires the committed
`webui/package-lock.json`, installs the pinned dependency graph with
`npm ci`, runs the dependency-pin check and creates the Vite production
build. It fails rather than falling back to an unlocked `npm install` if the
lockfile is absent. The ISO build copies `webui/dist/` into
`/usr/share/cockpit/feclora`.

The frontend invokes only fixed actions through the root-owned
`/usr/libexec/feclora/cockpit-api` wrapper. Requests are bounded JSON on
stdin. Cockpit superuser authorization is required for privileged operations.
No arbitrary shell or argv is exposed by the Feclora API.

Remote whole-disk and partition cloning are available as distinct unicast jobs in the
existing persistent Server/Client lifecycle. The Server selects a read-only
source disk and selects the Client MAC for this job; the Client selects and
confirms its local destination. The Client verifies the Server certificate. Deployment jobs use the reported
Client MAC address for selection and status association, alongside the durable job journal and managed
services. Clone streams directly between block devices through the existing
bounded remote-clone engine; it does not use UDPcast or create a second
service stack. Server-side byte progress is exposed through the existing
per-Client job status. The remote clone protocol header identifies the device type; the partition path copies exactly the source partition length and verifies receiver read-back. Real two-host acceptance remains outstanding.
