# Cockpit web interface

Cockpit is Feclora's primary operator interface. The React/PatternFly
application is installed at `/usr/share/cockpit/feclora` and uses Cockpit's
authenticated session and explicit superuser authorization for privileged
operations.

## Live kiosk startup, bootstrap and authentication

The Live image uses Fedora's Server product environment with no general-purpose
desktop. Cage is the minimal Wayland compositor; Firefox is the only local
interactive application. `feclora-kiosk.service` starts it on tty1 under the
dedicated `feclora-kiosk` account. The kiosk account has no login shell, is
not a member of `wheel`, and cannot invoke the privileged Feclora API.

The `feclora` administrator account is created as a member of `wheel`, but
starts locked. On each fresh Live boot, Firefox opens the first-boot assistant
at `http://127.0.0.1:8765/`. This service binds only to IPv4 loopback and
checks the Host header, exact Origin and a short-lived CSRF token. It accepts
a password of 14–128 characters, sends it to `chpasswd` through standard
input (never command-line arguments or logs), marks setup complete for the
current Live session, and redirects Firefox to the Feclora Cockpit application at
`https://localhost:9090/cockpit/@localhost/feclora/index.html`.
There is no default/shared administrator password.

The Live filesystem is currently ephemeral: the administrator password,
first-boot marker and generated local CA/private keys are lost on reboot.
Consequently the setup assistant runs again on every fresh Live boot. A
persistent configuration/credential store is a separate design requirement;
Feclora must not silently choose one of the disks that may be a restore target
as its persistence device.

Before Cockpit's socket is activated, a root-owned systemd oneshot generates
a local CA and a server certificate with SANs for `localhost`,
`127.0.0.1` and `::1`. The CA is installed in the Fedora system trust store and explicitly
installed into Firefox using its Linux enterprise certificate policy. Cockpit receives the
certificate and private key as separate files in
`/etc/cockpit/ws-certs.d/50-feclora.cert` and
`50-feclora.key`; private keys are root-only. Firefox does not bypass TLS
warnings or accept an untrusted certificate interactively.

Firefox runs with `--kiosk` and a managed enterprise policy. Firefox's
`WebsiteFilter` blocks all URLs except the loopback setup page and the local
Cockpit host. Firefox match patterns do not constrain port numbers, so these
loopback hosts are allowed on any port. Independently, systemd's cgroup IP
filters restrict both the kiosk browser and bootstrap service to IPv4/IPv6
loopback; the browser cannot open connections to LAN or Internet addresses. Password storage, private browsing,
developer tools, add-ons management, Safe Mode and certificate-warning
bypass are disabled. The local
CA is installed through Firefox's supported Linux `Certificates.Install`
policy and separately into Fedora's system trust store. The Cage/Firefox systemd service
restarts after failure. Cage is launched without its `-s` option (which would
enable VT switching), and getty services on tty1–tty6 are masked.

This is defense in depth, not a claim of tamper-proof physical kiosk
security. Firmware/boot-menu access and hardware-level keyboard escape
behavior still require operator testing. The authenticated Cockpit Terminal
remains available to the administrator inside Cockpit; the kiosk account
itself cannot log in to Cockpit as an administrator. Do not treat fullscreen
browser mode as a substitute for Cockpit authentication or backend
authorization.

## Build and package

On the Fedora 45 build host, install Node.js and npm with
`build/install-host-deps.sh`. The Live build invokes
`build/build-webui.sh`, which installs the frontend dependencies and builds
`webui/dist/`. The generated package is staged on the augmented installer
media and installed at `/usr/share/cockpit/feclora`.

The target image includes `cockpit`, `cockpit-system`,
`cockpit-storaged`, `cage` and `firefox`; it does not install a desktop
environment. `cockpit.socket`, the certificate/bootstrap units and the kiosk
unit are enabled by Kickstart. The Cockpit socket drop-in resets the default
wildcard listener and binds port 9090 only to `127.0.0.1` and `::1`; remote
LAN access is intentionally unavailable in this kiosk profile.

## Storage workflows

The Operations wizard provides:
- whole-disk, partition and active LVM logical-volume image capture;
- whole-disk, partition and existing-LV image restoration;
- whole-disk and partition-to-partition cloning;
- device discovery, image selection, compression selection and typed
  destructive confirmation;
- streamed byte-progress events from the storage engine;
- LVM capture and restore are limited to active, uniquely identified logical volumes in healthy volume groups; hidden, snapshot, RAID, striped, cache and unknown LV layouts are excluded. Restore overwrites data in an existing unmounted LV and does not create or resize LVM metadata. Raw LV images receive exact read-back verification; Partclone images receive a filesystem-specific read-only consistency check.
- optional image-security key initialization and age encryption when
  configured; artifact integrity is recorded and verified with SHA-256;
- durable local operation history, with a Cancel control for queued,
  preflight and running jobs, plus JSON export of the latest 100 loaded records.
  The history also reconciles the Live PXE restore journal, including interrupted
  results; PXE entries are read-only and cannot be cancelled through this view.

The Operation history tab can request cancellation of queued, preflight or
running local jobs. Feclora stops the worker and waits for its storage child
processes to exit before completing cancellation. Cancellation does not roll
back disk writes: a cancelled restore or clone may leave its destination
partially written, and the history records this warning. Jobs in verification
or terminal states cannot be cancelled.

The browser calls the same Python storage engines as the rest of Feclora.
The root-owned `/usr/libexec/feclora/cockpit-api` wrapper accepts a fixed
allowlist of actions. Requests are bounded JSON on stdin; device paths,
operation parameters, image identifiers and typed confirmations are
validated again by the backend. No shell or arbitrary command execution is
exposed through the API. Optional image-security keys are generated or installed for the current Live
session under `/etc/feclora/pki`. That directory is ephemeral in the default
Live appliance. Before reboot, the operator must preserve any age identity
needed to decrypt existing images. Losing an age identity
makes images encrypted to it unrecoverable. Age is not required for basic
local imaging.

## Current scope and limitations

The Cockpit application currently exposes local imaging operations, storage
inventory, image inventory, deployment journal summaries and system status.
Cockpit now includes an initial Server identity bootstrap step. It discovers
active IPv4 interface addresses, warns when NetworkManager reports an existing
DHCP server, verifies the selected address is still assigned to the interface,
and initializes or validates the managed CA and Server TLS identity, plus any
optional age recipient/signing material configured by the operator, without
enabling DHCP/PXE services.

The Server setup tab also provides a PXE network-profile preflight. It
validates ProxyDHCP or explicitly confirmed isolated DHCP, checks pool bounds,
verifies the selected interface and runs dnsmasq/Caddy configuration tests.
It reports an existing DHCP server when NetworkManager has lease information
and blocks isolated authoritative DHCP in that case. A missing DHCP lease
identifier is not proof of an isolated network. This step does not start
services, alter firewall rules or persist a network profile.

The Server **Remote jobs** tab now provides the persistent deployment
lifecycle for supported jobs. Cockpit can start a non-boot-enabled
`feclora-deployment@<UUID>.service`, inspect its Server-authenticated TLS listener and live
per-Client READY/running/terminal states, disk-operation byte progress and
sampled throughput reported over each authenticated TLS control session, with
Cockpit refreshing active service status every two seconds. The Client's local
status also tracks image-transfer phase and byte count. During restore, the Server
also records the sender-side artifact byte count and throughput in the existing
journal using a local progress callback; no telemetry frames are injected into
the TLS artifact stream. Operators can explicitly arm a job after every selected Client is
READY, cancel only before arming, and stop the service when it is not
performing storage I/O. The service uses the existing
coordinator, hash-chained journal, TLS control protocol and transfer engines;
the local IPC socket accepts root peers only and validates the exact job UUID
and typed confirmation.

Unicast whole-disk capture and disk/partition restore are supported by
the Cockpit Server/Client services. Cockpit multicast restore now uses the
persistent Client service: each Client selects its own receive interface and
local destination, passes interface/route/udp-receiver preflight, approves
the exact destructive target, and reports READY only after those checks.
The Server derives the total staging requirement from the verified
manifest and includes it in the authenticated job offer. Before reporting READY,
each Client compares that requirement with free space in its configured image
repository and requires an additional 64 MiB safety reserve. A failed or
unavailable capacity check prevents READY; the runtime repeats a capacity check
before receiving artifacts. This is a point-in-time preflight, so operators must
avoid concurrent use of the staging filesystem during deployment.
The Server can require every selected Client, a configured minimum READY count, or a UTC deadline with at least one READY Client. The deadline opens the start gate but never starts disk I/O automatically: the Server operator must still enter the exact job-specific authorization. Only Clients READY at arm time are dispatched. Each Client stages
and verifies every artifact's manifest/digest and any configured encryption
before writing its local disk.
Confirm switch IGMP snooping and an active querier on the same VLAN before
arming. UDPcast data packets themselves are not encrypted or authenticated;
Server-authenticated TLS protects the control channel, not the multicast payload. Multicast
capture and concurrent unicast deployments remain out of scope.

The Server service is never enabled at boot and never resumes an interrupted
job. A stop request closes the local IPC listener first, refuses new arm
requests, and waits for an active storage worker to reach its own terminal
state before closing Client sessions; its systemd stop timeout is therefore
unbounded. Interrupted journals require operator inspection and audit-only
reconciliation. Client-local target approval remains mandatory before READY.
The old dialog-based modules are migration-era code and are not part of the
supported Cockpit workflow.

No ISO build, hardware restore, PXE boot or multi-machine laboratory test is
claimed by source-level checks.

## Client remote jobs

On a configured Client, the **Client jobs** tab can inspect a Server job over
Server-authenticated TLS. The Client does not present a certificate or authenticate individually. It then
lists local disks/partitions, displays the exact Server-bound authorization
phrase, and starts a non-boot-enabled `feclora-client@<UUID>.service`.
The Client repeats the Server-authenticated TLS job handshake, rechecks the selected
block device against live inventory and mounted/root-device safety, and only
then reports READY. It waits for the Server's explicit ARM command before
starting disk I/O. Cockpit can inspect the Client's phase, target description,
byte progress and terminal result after the browser disconnects.

The Cockpit Client service supports unicast whole-disk capture, whole-disk
and partition restore, plus multicast restore of images using the configured artifact-security policy. A host
runs only one storage/deployment job at a time across Server, Client and local
Cockpit operations.
Interrupted Client services are marked for inspection and are never
automatically reconnected or resumed. An orderly systemd stop is deferred
while the Client is in its storage-I/O phase; the unit has no stop timeout that
could kill an active write. To cancel a Client that is waiting for ARM, cancel
the unarmed job from the Server Cockpit. For multicast restore, each
Client selects its own active IPv4 interface/address before authenticated
job inspection. Feclora binds the preflight and persistent unicast TLS session
to that source address and revalidates it before connecting. Multicast restore
also uses the selected interface for the receiver preflight before READY.
The next hop and policy routing remain controlled by the Client kernel routing
table; per-job route-table overrides are not yet exposed. No automatic poweroff/reboot is performed.

## PXE service lifecycle

Cockpit can now activate and stop a preflighted PXE profile. Activation stages
the boot tree, validates the selected interface and generated daemon
configurations, creates transient dnsmasq and Caddy systemd units, and opens a
temporary firewalld zone bound exclusively to the selected interface. The
unit names and firewall restoration metadata are recorded in a private
runtime-state file so a later Cockpit API process can stop the same services.
The services are not enabled at boot.

Use **Stop PXE services and restore firewall** when network boot is no longer
needed. If shutdown reports an incomplete cleanup, inspect systemd and
firewalld before retrying; do not manually delete the runtime-state file while
the temporary zone or services may still exist. Isolated authoritative DHCP
must only be activated on a dedicated VLAN where Feclora is the sole DHCP
server. A missing DHCP server in the NetworkManager lease is not proof of
network isolation.

## Optional age recipient inventory

When age encryption is enabled, the Server setup tab can export the current
public recipient inventory. Each Client can refresh its local recipient list
from that public inventory after verifying that it includes the Client's own
age identity. Private age identities remain local. This manages image
confidentiality recipients only; it is not Client authentication or revocation.

## Cockpit deployment-job API

The Server Cockpit API can validate and persist a deployment-job definition in the
root-owned hash-chained journal. Creation validates selected Client MACs, the
selected interface and image type, and validates manifest SHA-256 digests and authenticates any
age-encrypted artifact when present. Age recipient registrations are required only when the operator selects encryption
for a specific image.
Persisting a job does not contact Clients, arm the job, or start disk I/O.
The persistent systemd service can now load a fresh definition, verify its
journal/configuration, bind the Server-authenticated TLS listener and expose root-only local
IPC to Cockpit. It owns one active job at a time and continues if the browser
disconnects. It refuses interrupted journals and never recreates TLS sessions
or resumes storage work after a service/process restart.

## Remote deployment job definitions

The **Remote jobs** tab creates and lists validated Server-side job definitions.
For restore, select an existing disk or partition image; signed and unsigned
images are both available. Select Client MAC addresses for this job, the
Server interface and unicast or multicast restore transport. The backend
revalidates job MAC selection and image type, verifies a detached signature when one
is present, and checks registered age recipients only when the image is
age-encrypted. Manifests are transferred over the Server-authenticated TLS control session; Clients are not individually authenticated. If a Client
chooses to sign, its public key must be enrolled so the Server can verify it.

The persisted-job table also shows each Client's last journaled state,
the event count and whether a job was interrupted. After inspecting every
Client and destination manually, the operator can close an interrupted journal
for audit by entering the exact `RECONCILE <job-UUID>` phrase. This records
that manual inspection occurred; it does not resume, retry, roll back or touch
any storage device. The action is rejected for non-interrupted jobs.

Unicast save/restore jobs are limited to one Client. Direct disk/partition
clone jobs can target multiple selected Clients over independent TLS sessions;
the Server serializes reads from its single source, while each Client retains
its own local target approval and read-back verification. UDPcast multicast
restore requires at least two selected Clients. Physical-device multicast
clone is a separate feature and is not implemented yet.

For each fresh job, use **Start / connect service** to start its
non-boot-enabled `feclora-deployment@<UUID>.service` instance. The service
holds the Server-authenticated TLS listener and journal independently of the browser. Clients
verify the Server certificate, then select a local target and type
its destructive/read confirmation through the Cockpit **Client jobs** tab
before reporting READY. For multicast, each Client also selects its receive
interface and confirms the VLAN's IGMP snooping/querier configuration.
Cockpit exposes three start policies: manual (all selected Clients READY),
minimum READY count, or a UTC deadline (at least one Client READY). The deadline
opens the start gate but never starts storage I/O automatically. Only READY
Clients at arm time are dispatched. The Server operator must still enter the
exact job-specific phrase: `ARM <UUID>` for unicast save/restore,
`ARM <UUID> AND READ /dev/<source>` for direct clone, or
`ARM MULTICAST <UUID> IGMP-VERIFIED` for multicast restore, then select
**Arm and execute**. Each successful remote restore/clone Client can be
configured independently to do nothing, reboot or power off after its own
write/read-back verification and after reporting its terminal result. Failed
Clients are never rebooted or powered off.

Cancellation is intentionally limited to the unarmed state. Feclora does not
offer a button that pretends to interrupt a disk write already in progress.
The service cannot be stopped while its worker or any Client is actively
writing. If the service exits during an armed/running job, the journal remains
interrupted and must be manually inspected/reconciled; it is never restarted
automatically. The service supports one job per Server at a time and is not
enabled at boot. Multicast preflight reports local interface/route warnings,
but switch IGMP snooping/querier and VLAN isolation still require operator
validation. UDPcast multicast data is not encrypted or authenticated; only
the control plane uses Server-authenticated TLS; Clients are not authenticated individually.

## Optional age recipient inventory refresh

When age encryption is enabled, the Server trust panel can export the current public `age-recipients.txt` to mounted removable media without overwriting an existing file. Each remaining Client verifies that the inventory includes its own age identity before refreshing the local recipient list. Private identities remain local. This workflow is optional; deployments that do not use age do not need recipient inventories.

## Partition extraction

The image repository panel also exposes extraction of a selected partition from a whole-disk image. The operator selects a disk image, reviews a verified read-only partition-table preview (including start sectors and sizes), and selects the unambiguous partition node from the preview (the underlying engine also accepts PARTUUID and PARTLABEL selectors). Feclora verifies the source manifest and any configured authenticity evidence, decrypts and decompresses the disk artifact as needed, extracts the exact byte range, and publishes a separate partition manifest/artifact transactionally. If the source artifact was age-encrypted, the extracted partition artifact is re-encrypted only when the optional age feature is enabled and recipients are configured. The source image is never modified.

Disk restore also presents a read-only layout preview after selecting a signed/unsigned whole-disk image and destination disk. It verifies the manifest and partition-table artifact, displays the source partitions and compares the source image size with the selected target capacity. The current restore preserves the captured partition layout; larger target disks retain unused trailing capacity. No automatic partition or filesystem growth is performed.

Cockpit image inventory provides an on-demand read-only verification report for every artifact. It verifies stored artifact SHA-256 and size, age authentication when the artifact is age-encrypted, compression integrity and decoded whole-disk size. Images are reported as verified only when every stored digest and decoded artifact check succeeds.

Client certificates and Client certificate renewal are not used. Cockpit
reports the expiry of the locally configured Server TLS certificate and its
deployment CA. This is read-only; Server certificate renewal remains available
in the Server setup tab.

Cockpit also reports the local managed Server TLS certificate expiry and the associated deployment CA expiry. Certificates with 30 days or fewer remaining are flagged for renewal; expired Server or CA certificates and configuration/inspection errors are surfaced as critical status. This is read-only and does not rotate certificates automatically.

Server TLS certificate renewal is also available in the Cockpit Server setup tab. It requires typing `RENEW SERVER CERTIFICATE`, refuses to proceed while any deployment service is active, renews the certificate using the existing CA and Server private key, verifies the resulting chain, SAN and key match, and atomically replaces `server.crt`. The CA and Server identity remain unchanged. This is certificate renewal, not CA rotation or Server key rotation.

## Network configuration status

Cockpit's privileged API can now enumerate NetworkManager connection profiles
through a read-only, JSON-based inventory. The response is sanitized to expose
only profile identity, interface/device, autoconnect state and IPv4 method,
addresses, gateway and DNS; Wi-Fi credentials and other secret properties are
never returned. This is an inventory foundation, not yet a DHCP/static
configuration workflow: Cockpit does not modify connection profiles, switch
Server or Client addressing, or perform connectivity verification/rollback.
Do not treat the DHCP/static Server-and-Client requirement as complete.

### DHCP and static IPv4 profile application

The Network tab exposes active NetworkManager profiles on the current host
(Server or Client) and can apply DHCP or static IPv4 settings. Static mode
validates the address, prefix, gateway and DNS values before changing the
selected profile. Activation is performed inside a NetworkManager checkpoint
with a 120-second automatic rollback deadline. Feclora verifies the selected
profile and resulting IPv4 address before destroying the checkpoint; failures
request an immediate rollback. If Cockpit disconnects or the API process is
interrupted, NetworkManager's checkpoint timeout remains the recovery path.

Only profiles currently attached to a device are selectable. Keep local
console access available during changes, especially when changing the
management interface. This workflow currently covers IPv4 only; IPv6, Wi-Fi
secret provisioning, inactive profile binding and multi-interface routing
policy are not configured here.

## Remote repository credentials

See [Remote image repositories](REMOTE-REPOSITORIES.md) for the Cockpit encrypted-credential import, selection, rotation and removal workflow.

## Optional image security and repository transports

Feclora does not sign image manifests or use detached signature sidecars. Artifact integrity is checked with the byte count and SHA-256 digest recorded in the manifest; authenticity relies on the protected local repository and authenticated transport. Age encryption remains optional.

Remote repository types are SSHFS, NFS and SMB/CIFS mounted filesystems, plus S3 object storage through its HTTPS API. Cockpit exposes the mounted-provider and S3 object-repository workflows separately; S3 is not mounted as a filesystem.

For Server/Client deployment jobs, the persistent Cockpit Client can select an existing local logical volume for capture or restore when the job target type is `logical_volume`. Capture runs the manifest-backed LV planner and existing safe capture pipeline; restore validates healthy local LVM topology and repeats its preflight immediately before writing. Neither path creates or resizes LVM metadata.
