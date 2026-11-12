# Feclora Cockpit application

Feclora's React/PatternFly application is its primary operator interface.

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Other tabs provide durable local operation history, SSHFS/NFS/SMB repository
management and image-engine integration, signed-image SFTP inventory/import/
publication, Server CA and TLS trust configuration, optional age recipient
management, Server deployment-job authoring/lifecycle, Client job inspection
and execution, DHCP/static IPv4 profile configuration, PXE preflight and
service activation, and system status. Server/Client storage jobs use
READY/ARM authorization gates. PXE service activation and unattended answer
publication are explicit operations. Cockpit Terminal provides system
administration and diagnostic shell access.

Build the frontend from the repository root with
`bash build/build-webui.sh`. The script installs dependencies and runs the
Vite production build; it uses `npm ci` when a `webui/package-lock.json`
exists and currently falls back to `npm install` because the repository does
not yet commit that lockfile. The ISO build copies `webui/dist/` into
`/usr/share/cockpit/feclora`.

The frontend invokes only fixed actions through the root-owned
`/usr/libexec/feclora/cockpit-api` wrapper. Requests are bounded JSON on
stdin. Cockpit superuser authorization is required for privileged operations.
No arbitrary shell or argv is exposed by the Feclora API.

Remote whole-disk and partition cloning are available as distinct unicast jobs in the
existing persistent Server/Client lifecycle. The Server selects a read-only
source disk and selects the Client MAC for this job; the Client selects and
confirms its local destination. The Client verifies the Server certificate;
neither endpoint uses Client certificates. Both use the existing
Server-authenticated TLS control session, durable job journal and managed
services. Clone streams directly between block devices through the existing
bounded remote-clone engine; it does not use UDPcast or create a second
service stack. Server-side byte progress is exposed through the existing
per-Client job status. The remote clone protocol header identifies the device type; the partition path copies exactly the source partition length and verifies receiver read-back. Real two-host acceptance remains outstanding.
